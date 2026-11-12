"""Google Antigravity (agy, Gemini) hesapları arasında geçiş ve kota okuma.

agy girişini Windows Kimlik Yöneticisi'nde tek bir kayıtta tutar: 'gemini:antigravity' (JSON: token ve
id_token_email). Birden çok Gemini hesabı için her hesabın kaydı kendi adıyla saklanır
('claude-account-switcher:agy:<eposta>', aynı yerde, DPAPI korumalı: düz dosyada anahtar yok); geçiş,
canlı kaydın üzerine seçilen hesabın kaydını yazmaktır. cswap'ın Claude için yaptığıyla aynı fikir.

  Geçmeden önce canlı kayıt (agy'nin yenilediği token'larla) hesabın kendi yedeğine geri alınır: yedek
  bayatlayıp yenileme anahtarı geçersiz kalmasın.
  Yeni hesap: mevcut hesap yedeklenir, canlı kayıt kaldırılır, agy argümansız açılır (agy: "Launch the CLI
  without arguments to sign in"); giriş bitince panel yeni hesabı algılar, Kaydet ile yedeklenir.
  Kota: `agy -p "/usage"` (yaklaşık 5 sn) her hesap için 5 saatlik ve haftalık kalan yüzdeyi verir. Hesap
  etkin değilken okunamaz: pasif hesapta son okuma gösterilir (geçişten önce ve Kaydet'te okunur).

Terminalden: py agy_hesap.py durum | kota | kaydet [ad] | gec <eposta> | sil <eposta> | yeni
Testler gerçek girişe dokunmasın diye hedef adları ortamdan değişir: AGY_HESAP_CANLI, AGY_HESAP_YEDEK_ONEKI,
AGY_HESAP_VERI, AGY_HESAP_KOTA (kota komutu yerine kullanılacak program).
"""
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime, timezone

CANLI = os.environ.get('AGY_HESAP_CANLI', 'gemini:antigravity')
YEDEK_ONEKI = os.environ.get('AGY_HESAP_YEDEK_ONEKI', 'claude-account-switcher:agy:')
VERI = os.environ.get('AGY_HESAP_VERI') or os.path.join(
    os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'claude-account-switcher')
META = os.path.join(VERI, 'agy-hesaplar.json')
BOS = os.path.join(VERI, 'bos')            # agy kota okurken/açılırken çalışacağı boş klasör
KULLANICI = 'antigravity'                   # canlı kaydın kullanıcı alanı (agy yazıyor)
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010
ERROR_NOT_FOUND = 1168
EPOSTA = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,255}$')
kilit = threading.RLock()                   # kayıt değiştiren ve kota okuyan her işlem sırayla


# ── Windows Kimlik Yöneticisi ──────────────────────────────────────────────────────────────────

class _FILETIME(ctypes.Structure):
    _fields_ = [('lo', wintypes.DWORD), ('hi', wintypes.DWORD)]


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
                ('Comment', wintypes.LPWSTR), ('LastWritten', _FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
                ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


_adv = ctypes.WinDLL('advapi32', use_last_error=True)
_adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))]
_adv.CredReadW.restype = wintypes.BOOL
_adv.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), wintypes.DWORD]
_adv.CredWriteW.restype = wintypes.BOOL
_adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
_adv.CredDeleteW.restype = wintypes.BOOL
_adv.CredFree.argtypes = [ctypes.c_void_p]


def _oku(hedef):
    """(blob baytları, kullanıcı adı) ya da kayıt yoksa None."""
    p = ctypes.POINTER(_CREDENTIAL)()
    if not _adv.CredReadW(hedef, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        if ctypes.get_last_error() == ERROR_NOT_FOUND:
            return None
        raise OSError('Kimlik Yöneticisi okunamadı (kod %d).' % ctypes.get_last_error())
    try:
        c = p.contents
        blob = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize) if c.CredentialBlobSize else b''
        return bytes(blob), c.UserName or KULLANICI
    finally:
        _adv.CredFree(p)


def _yaz(hedef, blob, kullanici):
    tampon = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    c = _CREDENTIAL()
    c.Type = CRED_TYPE_GENERIC
    c.TargetName = hedef
    c.CredentialBlobSize = len(blob)
    c.CredentialBlob = ctypes.cast(tampon, ctypes.POINTER(ctypes.c_ubyte))
    c.Persist = CRED_PERSIST_LOCAL_MACHINE
    c.UserName = kullanici
    if not _adv.CredWriteW(ctypes.byref(c), 0):
        raise OSError('Kimlik Yöneticisi\'ne yazılamadı (kod %d).' % ctypes.get_last_error())


def _sil(hedef):
    if not _adv.CredDeleteW(hedef, CRED_TYPE_GENERIC, 0) and ctypes.get_last_error() != ERROR_NOT_FOUND:
        raise OSError('Kimlik Yöneticisi kaydı silinemedi (kod %d).' % ctypes.get_last_error())


def eposta_of(blob):
    """Kaydın hesabı (küçük harf e-posta); agy kaydı değilse None."""
    try:
        j = json.loads(blob.decode('utf-8'))
        e = str(j['id_token_email']).strip().lower()
        if EPOSTA.match(e) and (j.get('token') or {}).get('refresh_token'):
            return e
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError):
        pass
    return None


def _yedek_hedefi(eposta):
    return YEDEK_ONEKI + eposta.lower()


# ── Meta (yalnız ad, kota görüntüsü; gizli bilgi yok) ───────────────────────────────────────────

def _meta_oku():
    try:
        with open(META, encoding='utf-8') as f:
            m = json.load(f)
        if isinstance(m, dict) and isinstance(m.get('hesaplar'), dict):
            return m
    except (OSError, ValueError):
        pass
    return {'hesaplar': {}}


def _meta_yaz(m):
    os.makedirs(VERI, exist_ok=True)
    gecici = META + '.yeni'
    with open(gecici, 'w', encoding='utf-8') as f:
        json.dump(m, f, ensure_ascii=False, indent=1)
    os.replace(gecici, META)


def _simdi():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# ── agy ────────────────────────────────────────────────────────────────────────────────────────

def agy_yolu():
    return shutil.which('agy.exe') or shutil.which('agy')


_surec_onbellek = {'zaman': 0.0, 'sayi': 0}
_kota_suruyor = [0]


def acik_agy_sayisi():
    """Çalışan agy.exe sayısı (kota okuması hariç). Açık oturumlar eski hesabın girişini geri yazabilir."""
    if time.monotonic() - _surec_onbellek['zaman'] < 8:
        return _surec_onbellek['sayi']
    sayi = 0
    try:
        r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq agy.exe', '/FO', 'CSV', '/NH'], capture_output=True,
                           text=True, errors='replace', timeout=15, creationflags=CREATE_NO_WINDOW)
        sayi = sum(1 for s in r.stdout.splitlines() if s.lower().startswith('"agy.exe"'))
    except (OSError, subprocess.SubprocessError):
        pass
    _surec_onbellek.update(zaman=time.monotonic(), sayi=max(0, sayi - _kota_suruyor[0]))
    return _surec_onbellek['sayi']


_GRUP_ADI = {'gemini models': 'Gemini modelleri', 'claude and gpt models': 'Claude ve GPT modelleri'}


def kota_coz(metin):
    """`agy -p "/usage"` çıktısı: 'grup<TAB>Five Hour|Weekly Limit Remaining<TAB>%<TAB>sıfırlanma' satırları."""
    gruplar = {}
    for satir in metin.splitlines():
        parca = [p.strip() for p in satir.split('\t')]
        if len(parca) < 4 or not parca[2].endswith('%'):
            continue
        try:
            kalan = max(0, min(100, round(float(parca[2].rstrip('%')))))
        except ValueError:
            continue
        pencere = 'bes_saat' if 'five hour' in parca[1].lower() else 'haftalik' if 'week' in parca[1].lower() else None
        if not pencere:
            continue
        g = gruplar.setdefault(parca[0], {'ad': _GRUP_ADI.get(parca[0].lower(), parca[0])})
        g[pencere] = {'kalan': kalan, 'sifirlanma': parca[3] or None}
    if not gruplar:
        raise RuntimeError(next((s.strip() for s in metin.splitlines() if s.strip()), '') or 'agy kota bilgisi vermedi.')
    return list(gruplar.values())


def kota_oku():
    """Canlı hesabın kotası (agy'yi çalıştırır, ~5 sn). Sonucu o hesabın meta kaydına da işler."""
    with kilit:
        komut = os.environ.get('AGY_HESAP_KOTA') or agy_yolu()
        if not komut:
            raise RuntimeError('agy bulunamadı (PATH\'te agy.exe yok).')
        os.makedirs(BOS, exist_ok=True)
        _kota_suruyor[0] += 1
        try:
            r = subprocess.run([komut, '-p', '/usage', '--output-format', 'text'], capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=60, cwd=BOS, creationflags=CREATE_NO_WINDOW,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise RuntimeError('agy kotayı 60 saniyede vermedi.')
        finally:
            _kota_suruyor[0] -= 1
        gruplar = kota_coz(r.stdout)
        canli = _oku(CANLI)
        eposta = eposta_of(canli[0]) if canli else None
        if eposta:
            m = _meta_oku()
            h = m['hesaplar'].get(eposta)
            if h is not None:
                h.update(kota=gruplar, kota_zamani=_simdi())
                _meta_yaz(m)
        return gruplar


def _taze_kota(h, simdi):
    """Pasif hesabın son okuması: sıfırlanma saati geçmiş pencere yenilenmiş sayılır (kalan 100)."""
    cikti = []
    for g in h.get('kota') or []:
        g2 = {'ad': g.get('ad')}
        for p in ('bes_saat', 'haftalik'):
            v = g.get(p)
            if not v:
                continue
            s = v.get('sifirlanma')
            gecti = False
            if s:
                try:
                    gecti = datetime.fromisoformat(s.replace('Z', '+00:00')) <= simdi
                except ValueError:
                    pass
            g2[p] = {'kalan': 100 if gecti else v.get('kalan'), 'sifirlanma': None if gecti else s, 'yenilendi': gecti}
        cikti.append(g2)
    return cikti


# ── Hesap işlemleri ────────────────────────────────────────────────────────────────────────────

def durum():
    """Panelin 10 sn'de bir okuduğu görüntü. Yalnız okur: ucuz (bir kayıt + bir küçük dosya)."""
    simdi = datetime.now(timezone.utc)
    kurulu = bool(agy_yolu())
    canli = _oku(CANLI)
    canli_eposta = eposta_of(canli[0]) if canli else None
    m = _meta_oku()
    hesaplar = []
    for eposta, h in m['hesaplar'].items():
        if _oku(_yedek_hedefi(eposta)) is None:
            continue  # yedek kaydı elle silinmiş: kayıt yok sayılır
        hesaplar.append({'eposta': eposta, 'ad': h.get('ad') or eposta.split('@')[0], 'aktif': eposta == canli_eposta,
                         'kota': _taze_kota(h, simdi), 'kota_zamani': h.get('kota_zamani'),
                         'eklendi': h.get('eklendi')})
    hesaplar.sort(key=lambda x: (not x['aktif'], x['ad'].lower()))
    return {'kurulu': kurulu, 'canli_var': canli is not None, 'canli_eposta': canli_eposta,
            'canli_gecersiz': canli is not None and canli_eposta is None,
            'canli_kayitli': canli_eposta in m['hesaplar'] if canli_eposta else False,
            'hesaplar': hesaplar, 'acik_agy': acik_agy_sayisi() if kurulu else 0}


def kaydet(ad=None, kota=True):
    """Şu anki agy girişini hesap olarak yedekler (ya da kayıtlıysa yedeğini tazeler)."""
    ad = (ad or '').strip()
    if len(ad) > 40 or any(ord(c) < 32 for c in ad):
        raise ValueError('Ad en çok 40 karakter olabilir.')
    with kilit:
        canli = _oku(CANLI)
        if canli is None:
            raise ValueError('agy\'de giriş yok: önce agy\'yi açıp Gemini hesabıyla giriş yap.')
        eposta = eposta_of(canli[0])
        if not eposta:
            raise ValueError('agy giriş kaydı tanınmadı (beklenen biçimde değil).')
        _yaz(_yedek_hedefi(eposta), canli[0], canli[1])
        if (_oku(_yedek_hedefi(eposta)) or (None,))[0] != canli[0]:
            raise RuntimeError('Yedek doğrulanamadı: kayıt yazılamadı.')
        m = _meta_oku()
        h = m['hesaplar'].setdefault(eposta, {'eklendi': _simdi()})
        if ad or not h.get('ad'):
            h['ad'] = ad or eposta.split('@')[0]
        _meta_yaz(m)
        mesaj = '%s kaydedildi (%s).' % (h['ad'], eposta)
        if kota:
            try:
                kota_oku()
            except Exception as e:  # kota okunamasa da hesap kaydedildi
                mesaj += ' Kota okunamadı: %s' % e
        return mesaj


def gec(eposta, zorla=False):
    """Canlı girişi kayıtlı bir hesapla değiştirir."""
    eposta = str(eposta or '').strip().lower()
    with kilit:
        hedef = _oku(_yedek_hedefi(eposta))
        if hedef is None or eposta_of(hedef[0]) != eposta:
            raise ValueError('%s kayıtlı değil.' % eposta)
        canli = _oku(CANLI)
        canli_eposta = eposta_of(canli[0]) if canli else None
        if canli_eposta == eposta:
            raise ValueError('%s zaten aktif.' % eposta)
        m = _meta_oku()
        if canli and canli_eposta not in m['hesaplar'] and not zorla:
            raise ValueError('Şu anki giriş kayıtlı değil: geçersen kaybolur. Önce "Bu girişi kaydet" de.')
        if canli_eposta in m['hesaplar']:
            # Ayrılan hesap: kotasını oku (pasifken okunamaz), agy'nin yenilediği token'ları yedeğe geri al.
            try:
                kota_oku()
            except Exception:
                pass
            canli = _oku(CANLI)  # kota okuması token'ı yenilemiş olabilir
            if canli and eposta_of(canli[0]) == canli_eposta:
                _yaz(_yedek_hedefi(canli_eposta), canli[0], canli[1])
        _yaz(CANLI, hedef[0], hedef[1] or KULLANICI)
        dogrula = _oku(CANLI)
        if not dogrula or eposta_of(dogrula[0]) != eposta:
            raise RuntimeError('Geçiş doğrulanamadı: canlı kayıt beklenen hesapta değil.')
        m = _meta_oku()
        if eposta in m['hesaplar']:
            m['hesaplar'][eposta]['son_aktif'] = _simdi()
            _meta_yaz(m)
        ad = m['hesaplar'].get(eposta, {}).get('ad') or eposta
        return 'Gemini hesabı değişti: %s. Açık agy oturumlarını kapatıp yeniden aç.' % ad


def sil(eposta):
    """Hesabın yedeğini ve kaydını siler. Canlı giriş (aktifse) etkilenmez, yalnız kayıtsız kalır."""
    eposta = str(eposta or '').strip().lower()
    with kilit:
        m = _meta_oku()
        if eposta not in m['hesaplar'] and _oku(_yedek_hedefi(eposta)) is None:
            raise ValueError('%s kayıtlı değil.' % eposta)
        _sil(_yedek_hedefi(eposta))
        ad = m['hesaplar'].pop(eposta, {}).get('ad') or eposta
        _meta_yaz(m)
        return '%s silindi. Geri eklemek için agy\'de o hesapla giriş yapıp "Bu girişi kaydet" de.' % ad


def agy_ac():
    """agy'yi argümansız, yeni bir konsol penceresinde açar: giriş yoksa agy girişi başlatır."""
    yol = agy_yolu()
    if not yol:
        raise ValueError('agy bulunamadı (PATH\'te agy.exe yok).')
    os.makedirs(BOS, exist_ok=True)
    subprocess.Popen([yol], cwd=BOS, creationflags=CREATE_NEW_CONSOLE, stdin=None)


def yeni_hesap():
    """Başka bir Gemini hesabıyla giriş için: mevcut giriş yedeklenir, canlı kayıt kaldırılır, agy açılır."""
    with kilit:
        canli = _oku(CANLI)
        if canli is not None:
            if not eposta_of(canli[0]):
                raise ValueError('agy giriş kaydı tanınmadı; yedeklenemeyeceği için kaldırılmadı.')
            kaydet(kota=False)  # yedek doğrulanmadan canlı kayıt silinmez (kaydet doğrular)
            _sil(CANLI)
        agy_ac()
        return ('Mevcut giriş yedeklendi ve agy\'den çıkıldı. Açılan agy penceresinde diğer Gemini hesabıyla giriş yap; '
                'bitince bu sekmede "Bu girişi kaydet" görünür. Vazgeçersen kayıtlı hesabın yanındaki Geç\'e bas.')


def _main(arg):
    islem = arg[0] if arg else 'durum'
    if islem == 'durum':
        print(json.dumps(durum(), ensure_ascii=False, indent=1))
    elif islem == 'kota':
        print(json.dumps(kota_oku(), ensure_ascii=False, indent=1))
    elif islem == 'kaydet':
        print(kaydet(arg[1] if len(arg) > 1 else None))
    elif islem == 'gec' and len(arg) > 1:
        print(gec(arg[1]))
    elif islem == 'sil' and len(arg) > 1:
        print(sil(arg[1]))
    elif islem == 'yeni':
        print(yeni_hesap())
    else:
        print(__doc__.split('Terminalden:')[1].split('Testler')[0].strip())


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        _main(sys.argv[1:])
    except (ValueError, RuntimeError, OSError) as e:
        print('Hata: %s' % e, file=sys.stderr)
        sys.exit(1)
