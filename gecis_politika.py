"""Hesap geçiş politikası: Fable sınırı, hesap öncelik sırası ve geçişte hedef seçimi.

esikte-gec.py (durum satırından hızlı tetik ve sınır hatası kancası) hedefi buradan seçer; panel
(arayuz.pyw) ayarı buradan okur/yazar. Yalnız stdlib; cswap'a ve ağa dokunmaz.

Ayar dosyası: %LOCALAPPDATA%\\claude-account-switcher\\gecis-ayar.json (GECIS_AYAR ortam değişkeni yolu ezer):

    {"fable_esigi": 80, "oncelik_acik": true, "oncelik": ["a@x.com", "b@x.com"]}

  fable_esigi   Aktif hesabın Fable (modele özel haftalık) kullanımı bu yüzdeye gelince geçilir. Boşsa (None)
                Fable'a göre geçiş yok. Hedef seçerken de Fable'ı bu sınırın altında olmayan hesap elenir.
                Fable kullanımını cswap'ın deposu verir (durum satırında yok): Anthropic'e fazladan istek gitmez,
                ama değer cswap'ın okuma sıklığı kadar (1-3 dk) gecikmeli olabilir.
  oncelik_acik  Açıksa geçişte hedef öncelik listesine göre seçilir; kapalıysa bugünkü "en boş hesap".
  oncelik       Hesap e-postaları, en önemli en başta.

Öncelik davranışı (bilinmesi gerekenler):
  * Öncelik "aktiften sonraki hesap" değil, "listedeki ilk UYGUN hesap"tır: aktif dışındaki, iki eşiğin (ve varsa
    Fable sınırının) altındaki hesaplardan listede en öndeki seçilir. Aktifin listedeki yerine bakılmaz.
  * Listede olmayan uygun hesaplar sona kalır ve kendi aralarında "en boş" kuralıyla sıralanır.
  * Geri dönüş (failback) YOK: geçiş yalnız aktif hesap bir sınıra gelince ya da sınır hatasında yapılır. Öncelikli
    hesap sıfırlanıp boşalsa da, aktif hesap sınıra gelmedikçe oraya geri dönülmez.
  * Hepsi eşiğin üstündeyse (yalnız sınır hatasında, aktif_yuzde verildiğinde) yedek dal öncelikten bağımsız
    çalışır: en az dolu hesap; öncelik/Fable sınırı yedeği değiştirmez.
  * cswap auto'nun kendi geçişleri (strateji "best") öncelikten habersizdir; bu politika esikte-gec.py'nin
    geçişlerini (durum satırı eşiği, Fable sınırı, sınır hatası) yönetir.
"""
import json
import os
import re
from datetime import datetime

EPOSTA = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,255}$')
FABLE_ALT, FABLE_UST = 50.0, 99.9
ONCELIK_EN_COK = 200


def AYAR_YOLU():
    """Ayar dosyasının yolu. Ortamı her çağrıda okur (testler ve panel yolu sonradan değiştirebilsin)."""
    yol = os.environ.get('GECIS_AYAR')
    if yol:
        return yol
    kok = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(kok, 'claude-account-switcher', 'gecis-ayar.json')


def varsayilan():
    return {'fable_esigi': None, 'oncelik_acik': False, 'oncelik': []}


# ── Ayar doğrulama ─────────────────────────────────────────────────────────────────────────────

def _fable(v):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError('Fable sınırı bir sayı olmalı (ya da boş).')
    if not FABLE_ALT <= v <= FABLE_UST:
        raise ValueError('Fable sınırı %g ile %g arasında olmalı (veya boş bırakılmalı).' % (FABLE_ALT, FABLE_UST))
    return float(v)


def _acik(v):
    if v is None:
        return False
    if not isinstance(v, bool):
        raise ValueError('Öncelik anahtarı açık ya da kapalı olmalı.')
    return v


def _oncelik(v):
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError('Öncelik bir e-posta listesi olmalı.')
    sonuc = []
    for e in v:
        if not isinstance(e, str) or not EPOSTA.match(e.strip()):
            raise ValueError('Öncelik listesinde geçersiz e-posta: %r' % (str(e)[:60],))
        e = e.strip().lower()
        if e not in sonuc:
            sonuc.append(e)
    if len(sonuc) > ONCELIK_EN_COK:
        raise ValueError('Öncelik listesi en çok %d hesap olabilir.' % ONCELIK_EN_COK)
    return sonuc


def ayar_normalize(ham):
    """Ayarı doğrular ve normalize eder; geçersizse ValueError (Türkçe mesaj). Bilinmeyen alanlar atılır."""
    if not isinstance(ham, dict):
        raise ValueError('Ayar bir nesne olmalı.')
    return {'fable_esigi': _fable(ham.get('fable_esigi')),
            'oncelik_acik': _acik(ham.get('oncelik_acik')),
            'oncelik': _oncelik(ham.get('oncelik'))}


def ayar_oku():
    """Kayıtlı ayar. ASLA istisna atmaz: dosya yok/bozuksa varsayılan; geçersiz alan varsayılana düşer
    (geçiş yolu ayar yüzünden kırılmasın)."""
    ayar = varsayilan()
    try:
        with open(AYAR_YOLU(), encoding='utf-8-sig') as f:
            ham = json.load(f)
        if not isinstance(ham, dict):
            return ayar
        for alan, dogrula in (('fable_esigi', _fable), ('oncelik_acik', _acik), ('oncelik', _oncelik)):
            try:
                ayar[alan] = dogrula(ham.get(alan))
            except (ValueError, TypeError):
                pass
    except Exception:
        return varsayilan()
    return ayar


def ayar_yaz(ayar):
    """Ayarı doğrulayıp atomik yazar (geçici dosya + os.replace); normalize edilmişi döndürür."""
    temiz = ayar_normalize(ayar)
    yol = AYAR_YOLU()
    klasor = os.path.dirname(yol)
    if klasor:
        os.makedirs(klasor, exist_ok=True)
    gecici = '%s.%d.tmp' % (yol, os.getpid())
    try:
        with open(gecici, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(temiz, f, ensure_ascii=False, indent=1)
        os.replace(gecici, yol)
    except OSError:
        try:
            os.remove(gecici)
        except OSError:
            pass
        raise
    return temiz


# ── Kullanım okuma ve hedef seçimi ─────────────────────────────────────────────────────────────

def unix(iso):
    try:
        return datetime.fromisoformat(iso).timestamp() if iso else None
    except (TypeError, ValueError):
        return None


def kayit(satir, anahtar, simdi):
    """Kayıttaki pencere: (yüzde, sıfırlanma unix). Pencere bitmişse (0, None)."""
    w = (satir.get('usage') or {}).get(anahtar) or {}
    pct, r = w.get('pct'), unix(w.get('resetsAt'))
    if r is not None and r <= simdi:
        return 0.0, None
    return pct, r


def fable_yuzde(satir, simdi):
    """Hesabın Fable (modele özel haftalık) kullanımı; kayıtta yoksa None. Sıfırlanma saati geçmişse 0.0
    (pencere yenilenmiş, depodaki yüzde eski)."""
    for s in (satir.get('usage') or {}).get('scoped') or []:
        if str(s.get('name') or '').strip().lower() != 'fable':
            continue
        pct = s.get('pct')
        if pct is None:
            return None
        r = unix(s.get('resetsAt'))
        if r is not None and r <= simdi:
            return 0.0
        return float(pct)
    return None


def hedef_sec(hesaplar, aktif, simdi, esik, h_esik, aktif_yuzde, fable_esik=None, oncelik=None):
    """Geçilecek hesap satırı; yoksa None.

    Aday: aktif dışındaki, active/disabled olmayan, usageStatus 'ok' hesaplar. UYGUN aday: 5 saatlik < esik,
    haftalık < h_esik ve (fable_esik verilmişse) Fable'ı sınırın altında ya da okunamayan hesap (Fable'ı
    bilinmeyen hesap bu yüzden elenmez).

    Seçim: oncelik (küçük harf e-posta listesi) boşsa uygunlar arasında en boş (doluluk = max(5s/esik,
    hafta/h_esik)); eşitlikte listede önde olan. oncelik doluysa uygunlar arasında listede en öndeki; listede
    olmayanlar sona kalır ve kendi aralarında en boş kuralıyla sıralanır.

    Uygun hesap yoksa ve aktif_yuzde verilmişse (sınır hatası) yedek: aktiften en az 5 puan boş, sınıra
    dayanmamış (<%99) en az dolu hesap; sınıra çarpan hesapta beklemektense %96'daki hesabın kalan %4'ü
    kullanılsın. Eşik/Fable geçişinde (aktif_yuzde None) yedek yok: hepsi eşiğin üstündeyken cswap auto bilerek
    ilk sıfırlanacak hesaba gidiyor; burada en düşük yüzdeye dönmek onunla çekişip hesabı dakikada bir gidip
    getiriyordu (11.11 19:49-19:58, 8 ile 10 arasında). Fable sınırından elenen hesap uygun sayılmaz ama
    yedek dala girebilir (sınır hatasında Fable dışı modellerle kullanılabilir)."""
    sira = {e.strip().lower(): i for i, e in reversed(list(enumerate(oncelik or [])))}
    uygunlar = []  # (öncelik sırası, doluluk, liste sırası, satır)
    yedek = None
    for i, s in enumerate(hesaplar):
        if s is aktif or s.get('active') or s.get('disabled') or s.get('usageStatus') != 'ok':
            continue
        p5 = kayit(s, 'fiveHour', simdi)[0] or 0.0
        p7 = kayit(s, 'sevenDay', simdi)[0] or 0.0
        fable_ok = True
        if fable_esik is not None:
            pf = fable_yuzde(s, simdi)
            fable_ok = pf is None or pf < fable_esik
        if p5 < esik and p7 < h_esik and fable_ok:
            doluluk = max(p5 / esik, p7 / h_esik)
            rank = sira.get((s.get('email') or '').strip().lower(), len(sira)) if sira else 0
            uygunlar.append((rank, doluluk, i, s))
        elif aktif_yuzde is not None and max(p5, p7) < min(99.0, aktif_yuzde - 5) \
                and (yedek is None or max(p5, p7) < yedek[0]):
            yedek = (max(p5, p7), s)
    if uygunlar:
        return min(uygunlar, key=lambda t: t[:3])[3]
    return yedek[1] if yedek else None
