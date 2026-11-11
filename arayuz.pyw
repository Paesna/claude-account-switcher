"""Claude hesapları penceresi: her hesabın kullanımı, sıfırlanma saati ve son geçişler;
tıklayarak hesaba geçme, hesabı durdurma/açma, eşiği kaydetme ve hesap ekleme.

Masaüstündeki "Claude hesapları" kısayolu bunu pythonw ile başlatır. Sayfa yalnız
127.0.0.1'den dinleyen bir sunucudan gelir ve Chrome'un uygulama penceresinde açılır.
Her açılışta rastgele bir anahtar üretilir; anahtarı başlıkta taşımayan istek reddedilir.
Yoksa tarayıcıda açık herhangi bir web sayfası yerel sunucuya istek atıp hesap
değiştirebilirdi.

Pencere kapanırken sayfa haber verir, sunucu 90 sn sonra kapanır. Haber gelmezse
12 saat yoklama gelmeyince kapanır: Chrome simge durumundaki pencerenin zamanlayıcısını
gece boyu dakikaya bir indirebiliyor ya da donduruyor, sabah pencere kopmuş olmasın.

Bu dosya değişince sunucu kendini aynı port ve anahtarla yeniden başlatır; açık pencere
kopmadan yeni kodla sürer. 07.11'de sunucu 18:30'dan beri eski kodla çalışıyordu: sayfa
(her açılışta diskten okunur) haftalık eşiği gönderiyor, eski sunucu yok sayıyordu.
"""
import ctypes
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# Kod değişince eski süreç yenisine "port anahtar" devreder; alt süreçlere (cswap) geçmesin.
DEVIR = os.environ.pop('ARAYUZ_DEVIR', '').split()
KAYNAK = os.path.abspath(__file__)
KLASOR = os.path.dirname(KAYNAK)
SAYFA = os.path.join(KLASOR, 'arayuz.html')
ACIK_DOSYASI = os.path.join(KLASOR, 'arayuz.acik.json')
LOG = os.path.join(KLASOR, 'arayuz.log')
AUTO_LOG = os.path.join(KLASOR, 'cswap-auto.log')
HESAP_EKLE = os.path.join(KLASOR, 'hesap-ekle.ps1')
# Elle ve hızlı tetikle yapılan geçişler; otomatik olanlar cswap-auto.log'da.
GECIS_LOG = os.path.join(KLASOR, 'gecisler.log')
# İsteğe bağlı: durum satırından eşik komutu çalıştıran bir kota izleyicisi varsa
# (bu depoda değil) eski geçiş satırları ve eşiği oradan da okunur/yazılır.
ESKI_OLAYLAR = os.path.expanduser(r'~\.claude\kota\olaylar.log')
KOTA_AYAR = os.path.expanduser(r'~\.claude\kota\ayar.json')
CSWAP_AYAR = os.path.expanduser(r'~\.claude-swap-backup\settings.json')
CSWAP = os.path.expanduser(r'~\.local\bin\cswap.exe')
TARAYICILAR = [
    os.path.expandvars(r'%ProgramFiles%\Google\Chrome\Application\chrome.exe'),
    os.path.expandvars(r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe'),
    os.path.expandvars(r'%LocalAppData%\Google\Chrome\Application\chrome.exe'),
    os.path.expandvars(r'%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe'),
    os.path.expandvars(r'%ProgramFiles%\Microsoft\Edge\Application\msedge.exe'),
]
ORTAM = dict(os.environ, PYTHONUTF8='1')
CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183
MUTEX = 'Local\\claude-account-switcher-ui'
BOSTA_KAPAN_SN = 12 * 3600
KAPANDI_BEKLE_SN = 90
EPOSTA = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.CreateMutexW.restype = ctypes.c_void_p
k32.OpenMutexW.restype = ctypes.c_void_p
k32.CloseHandle.argtypes = [ctypes.c_void_p]

ANAHTAR = DEVIR[1] if len(DEVIR) == 2 else secrets.token_urlsafe(24)
son_istek = time.time()
ekleme = {}          # sürmekte olan hesap ekleme: eposta, durum, mesaj
islem_sayisi = 0     # yanıtı beklenen POST'lar: sürerken sunucu kapanmaz, devretmez
kilit = threading.Lock()


def log(metin):
    try:
        if os.path.getsize(LOG) > 1_000_000:
            os.replace(LOG, LOG + '.old')
    except OSError:
        pass
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + metin + '\n')
    except OSError:
        pass


def cswap(*arg, zaman=120):
    r = subprocess.run([CSWAP, *arg], capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=ORTAM, creationflags=CREATE_NO_WINDOW, timeout=zaman)
    return r.returncode, r.stdout, r.stderr


_liste = {'zaman': 0.0, 'veri': None}
_liste_kilit = threading.Lock()


def cswap_liste(taze=False):
    """cswap list --json (~1 sn, üç süreç). Aynı anda gelen yoklamalar tek çağrıyı paylaşır;
    sonuç 10 sn geçerli, bir işlemden sonra tazelenir."""
    with _liste_kilit:
        if not taze and _liste['veri'] is not None and time.monotonic() - _liste['zaman'] < 10:
            return _liste['veri']
        kod, cikti, hata = cswap('list', '--json', zaman=60)
        # cswap bir hesabın kullanımı okunamayınca listeyi yine yazıp sıfırdan farklı kodla
        # bitebiliyor (28.10 11:52); JSON geldiyse onu kullan. Hesap listesi olmayan JSON da
        # geliyor (06.11 13:18 KeyError 'accounts').
        try:
            veri = json.loads(cikti)
        except ValueError:
            veri = None
        if not isinstance(veri, dict) or not isinstance(veri.get('accounts'), list):
            raise RuntimeError('Hesap listesi okunamadı (kod %s): %s' % (kod, ilk_satir(hata, cikti)))
        _liste.update(zaman=time.monotonic(), veri=veri)
        return veri


def liste_bayat():
    with _liste_kilit:
        _liste['veri'] = None


def ilk_satir(*metinler):
    return next((s.strip() for m in metinler for s in m.splitlines() if s.strip()), '')


def esik_oku():
    saatlik = 90
    haftalik = None
    try:
        with open(CSWAP_AYAR, encoding='utf-8') as f:
            ayar = json.load(f).get('autoswitch', {})
            if 'threshold' in ayar and ayar['threshold'] is not None:
                saatlik = int(round(ayar['threshold']))
            if 'weeklyThreshold' in ayar and ayar['weeklyThreshold'] is not None:
                haftalik = int(round(ayar['weeklyThreshold']))
    except Exception:
        pass
    return saatlik, haftalik


def mutex_var(ad):
    h = k32.OpenMutexW(0x00100000, False, ad)  # SYNCHRONIZE
    if h:
        k32.CloseHandle(h)
        return True
    return False


def gorev_calisiyor():
    # cswap-auto.pyw tek kopyayı bu adlı mutex'le tutuyor; varsa görev ayakta.
    return mutex_var('Local\\claude-account-switcher-auto')


def gorevi_yeniden_baslat():
    # cswap auto eşiği ve hesap listesini başlarken okuyor; yeni ayar ancak yeniden
    # başlayınca geçerli olur.
    for arg in (['/End'], ['/Run']):
        subprocess.run(['schtasks', *arg, '/TN', 'cswap-auto'], capture_output=True,
                       creationflags=CREATE_NO_WINDOW)
        time.sleep(2)


def ad(eposta):
    return eposta.split('@')[0]


def hesaplar(esik, haftalik_esik=None):
    veri = cswap_liste()
    simdi = datetime.now(timezone.utc)
    satirlar = []
    for a in veri['accounts']:
        u = a.get('usage') or {}
        b, h = u.get('fiveHour'), u.get('sevenDay')
        yuzde = round(b['pct']) if b and b.get('pct') is not None else None
        h_yuzde = round(h['pct']) if h and h.get('pct') is not None else None
        sifir = None
        if b and b.get('resetsAt'):
            sifir = datetime.fromisoformat(b['resetsAt'])
            if sifir <= simdi:
                # Pencere sıfırlanmış, depo henüz tazelenmemiş: eski yüzde artık geçersiz.
                yuzde, sifir = 0, None
        h_sifir = None
        if h and h.get('resetsAt'):
            h_sifir = datetime.fromisoformat(h['resetsAt'])
            if h_sifir <= simdi:
                h_yuzde, h_sifir = 0, None
        saatlik_dolu = yuzde is not None and yuzde >= esik
        # Haftalık eşik boşsa cswap haftalık pencerede de 5 saatlik eşiği kullanıyor.
        h_sinir = haftalik_esik if haftalik_esik is not None else esik
        haftalik_dolu = h_yuzde is not None and h_yuzde >= h_sinir
        # Dolu hesap ne zaman yeniden kullanılabilir: haftalıkta doluysa 5 saatlik sıfırlansa da
        # açılmaz, haftalık sıfırlanmayı bekler; ikisi de doluysa geç olanı.
        acilma = max((t for t, dolu in ((sifir, saatlik_dolu), (h_sifir, haftalik_dolu)) if dolu and t),
                     default=None)
        if a.get('active'):
            durum = 'aktif'
        elif a.get('disabled'):
            durum = 'durduruldu'
        elif a.get('usageStatus') != 'ok' or yuzde is None:
            durum = 'okunamiyor'
        elif saatlik_dolu or haftalik_dolu:
            durum = 'dolu'
        else:
            durum = 'hazir'
        satirlar.append({
            'no': a['number'], 'eposta': a['email'], 'ad': ad(a['email']),
            'kurum': a.get('organizationName') or '', 'durum': durum,
            'durduruldu': bool(a.get('disabled')), 'aktif': bool(a.get('active')),
            'yuzde': yuzde, 'sifirlanma': sifir.isoformat() if sifir else None,
            'haftalik': h_yuzde,
            'haftalik_sifirlanma': h_sifir.isoformat() if h_sifir else None,
            'acilma': acilma.isoformat() if acilma else None,
            'saatlik_dolu': saatlik_dolu,
            'haftalik_dolu': haftalik_dolu,
            'hata': a.get('usageError') or '',
        })
    sira = {'aktif': 0, 'hazir': 1, 'dolu': 2, 'okunamiyor': 3, 'durduruldu': 4}
    satirlar.sort(key=lambda s: (sira[s['durum']],
                                 s['yuzde'] if s['durum'] == 'hazir' else 0,
                                 (s['acilma'] if s['durum'] == 'dolu' else s['sifirlanma']) or '9999', s['no']))
    return satirlar


def kuyruk(yol, bayt=400_000):
    """Günlüğün yalnız sonu (hesap ekleme adımı için)."""
    try:
        with open(yol, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - bayt))
            return f.read().decode('utf-8', errors='replace').splitlines()
    except OSError:
        return []


class Izleyici:
    """Günlüğün yalnız son okumadan beri eklenen kısmını verir; dosya dönünce (küçülünce) baştan.

    Eskiden her yoklamada her günlüğün son 400 KB'ı baştan okunup taranıyordu. 20 hesaplı
    cswap-auto.log'da bir tur ~2,5 KB: 400 KB yalnız son ~2,5 saatti, seyrek geçişler
    "Son geçişler"den düşüyordu. Şimdi ilk açılışta bütün dosya bir kez, sonra yalnız ekler okunur.
    """

    def __init__(self, yol):
        self.yol, self.konum, self.artik = yol, None, b''

    def yeni_satirlar(self):
        try:
            boyut = os.path.getsize(self.yol)
        except OSError:
            return []
        if self.konum is None or boyut < self.konum:
            self.konum, self.artik = 0, b''
        if boyut == self.konum:
            return []
        try:
            with open(self.yol, 'rb') as f:
                f.seek(self.konum)
                veri = f.read(boyut - self.konum)
        except OSError:
            return []
        self.konum += len(veri)
        satirlar = (self.artik + veri).split(b'\n')
        self.artik = satirlar.pop()  # yarım kalan son satır bir sonraki okumaya
        return [s.decode('utf-8', errors='replace').rstrip('\r') for s in satirlar]


NEDEN = {'proactive': 'eşikte', 'at-limit': 'doldu'}
OTOMATIK = re.compile(r'^(\S+)\s+\S+\s+Switched Account-(\d+) -> Account-(\d+) \(([^)]+)\)(?: \(([\w-]+)\))?')
BEKLEME = re.compile(r'^\S+\s+\S+\s+all accounts exhausted')
SAAT = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ')
ELLE = re.compile(r'cswap switch \((elle|[^)]*)\): Switched to Account-(\d+) \(([^)]+)\)')
_auto_izleyici = Izleyici(AUTO_LOG)
_el_izleyiciler = [[Izleyici(GECIS_LOG), None], [Izleyici(ESKI_OLAYLAR), None]]  # [izleyici, son saat]
_olaylar = {}
_olay_kilit = threading.Lock()


def _olay(o):
    # Hızlı tetik geçişi hem kendi günlüğüne hem kota izleyicisinin günlüğüne düşebilir.
    _olaylar[(o['zaman'], o.get('kime'), o['tur'])] = o


def gecisler(adlar):
    with _olay_kilit:
        for s in _auto_izleyici.yeni_satirlar():
            m = OTOMATIK.match(s)
            if m:
                _olay({'zaman': m.group(1)[:19], 'kimden_no': int(m.group(2)), 'kime': ad(m.group(4)),
                       'neden': NEDEN.get(m.group(5), m.group(5) or ''), 'tur': 'otomatik'})
            elif BEKLEME.match(s):
                _olay({'zaman': s[:19], 'tur': 'bekleme'})
        for kayit in _el_izleyiciler:
            for s in kayit[0].yeni_satirlar():
                m = SAAT.match(s)
                if m:
                    kayit[1] = m.group(1).replace(' ', 'T')
                m = ELLE.search(s)
                if m and kayit[1]:
                    elle = m.group(1) == 'elle'
                    neden = 'elle' if elle else ('sınır hatası' if 'sınır' in m.group(1) else 'hızlı tetik')
                    _olay({'zaman': kayit[1], 'kime': ad(m.group(3)),
                           'neden': neden, 'tur': 'elle' if elle else 'hizli'})
        olaylar = sorted(_olaylar.values(), key=lambda o: o['zaman'], reverse=True)
        if len(olaylar) > 300:
            for o in olaylar[300:]:
                _olaylar.pop((o['zaman'], o.get('kime'), o['tur']), None)
    # "Hepsi dolu" her 10 dakikada bir yazılıyor; ardışık olanlardan yalnız ilki kalır.
    sonuc = []
    for o in olaylar:
        if o['tur'] == 'bekleme' and sonuc and sonuc[-1]['tur'] == 'bekleme':
            sonuc[-1] = o
            continue
        o = dict(o)
        if 'kimden_no' in o:
            no = o.pop('kimden_no')
            o['kimden'] = adlar.get(no, '#%d' % no)
        sonuc.append(o)
        if len(sonuc) == 15:
            break
    return sonuc


_sayfa = {'surum': None}


def sayfa_surumu():
    """arayuz.html'in değişme zamanı; açık sayfa bunu görünce kendini yeniler.
    Dosya 20 sn durulmadan bildirilmez: yarım düzenlenmiş sayfa yüklenmesin."""
    try:
        m = os.path.getmtime(SAYFA)
        if _sayfa['surum'] is None or time.time() - m > 20:
            _sayfa['surum'] = m
    except OSError:
        pass
    return _sayfa['surum']


def durum():
    esik, haftalik_esik = esik_oku()
    liste = hesaplar(esik, haftalik_esik)
    with kilit:
        ek = dict(ekleme)
    if ek.get('durum') == 'suruyor':
        ek['adim'] = ekleme_adimi()
        ek['sure_dk'] = int((time.time() - ek.get('basladi', time.time())) // 60)
    with kilit:
        sifirlama = {k: v for k, v in sira.items() if k != 'iptal'}
    return {'esik': esik, 'haftalik_esik': haftalik_esik, 'gorev': gorev_calisiyor(), 'hesaplar': liste,
            'gecisler': gecisler({h['no']: h['ad'] for h in liste}), 'ekleme': ek, 'sifirlama': sifirlama,
            'pencere': pencere_durumu(),
            'saat': datetime.now().astimezone().isoformat(), 'sayfa': sayfa_surumu()}


def no_al(govde):
    try:
        return int(govde['no'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('Hesap numarası eksik.')


def gecisi_yaz(satir):
    with open(GECIS_LOG, 'a', encoding='utf-8') as f:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + 'cswap switch (elle): ' + satir + '\n')


def gec(govde):
    no = no_al(govde)
    kod, cikti, hata = cswap('switch', str(no))
    satir = ilk_satir(cikti, hata)
    if kod != 0:
        raise RuntimeError('Geçilemedi: ' + satir)
    gecisi_yaz(satir)
    return 'Geçildi. Açık oturumlar bir sonraki mesajda yeni hesapla devam eder.'


def en_iyi(_):
    kod, cikti, hata = cswap('switch', '--strategy', 'best')
    satir = ilk_satir(cikti, hata)
    if kod != 0:
        raise RuntimeError('Geçilemedi: ' + satir)
    gecisi_yaz(satir)
    return 'En boş hesaba geçildi.'


def durdur(govde):
    kod, cikti, hata = cswap('disable', str(no_al(govde)))
    if kod != 0:
        raise RuntimeError('Durdurulamadı: ' + ilk_satir(hata, cikti))
    return 'Durduruldu: otomatik geçiş bu hesaba gitmeyecek. Aktifse başka hesaba geçince bırakılır.'


def ac(govde):
    kod, cikti, hata = cswap('enable', str(no_al(govde)))
    if kod != 0:
        raise RuntimeError('Açılamadı: ' + ilk_satir(hata, cikti))
    return 'Açıldı: hesap yeniden sırada.'


def esik_kaydet(govde):
    try:
        yuzde = int(govde['yuzde'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('5 saatlik eşik bir sayı olmalı.')
    if not 50 <= yuzde <= 99:
        raise ValueError('5 saatlik eşik 50 ile 99 arasında olmalı.')

    haftalik_ham = govde.get('haftalik_yuzde')
    haftalik_yuzde = None
    if haftalik_ham is not None and str(haftalik_ham).strip() != '':
        try:
            haftalik_yuzde = int(haftalik_ham)
        except (TypeError, ValueError):
            raise ValueError('Haftalık eşik bir sayı olmalı.')
        if not 50 <= haftalik_yuzde <= 99:
            raise ValueError('Haftalık eşik 50 ile 99 arasında olmalı (veya boş bırakılmalı).')

    kod, cikti, hata = cswap('config', 'set', 'autoswitch.threshold', str(yuzde))
    if kod != 0:
        raise RuntimeError('5 saatlik eşik kaydedilemedi: ' + ilk_satir(hata, cikti))

    if haftalik_yuzde is not None:
        kod, cikti, hata = cswap('config', 'set', 'autoswitch.weeklyThreshold', str(haftalik_yuzde))
        if kod != 0:
            raise RuntimeError('Haftalık eşik kaydedilemedi: ' + ilk_satir(hata, cikti))
    else:
        # Boş bırakıldıysa haftalık eşiği kaldır
        cswap('config', 'unset', 'autoswitch.weeklyThreshold')

    # Durum satırındaki hızlı tetik (varsa) aynı eşikte çalışsın; ayrışırsa biri erken biri geç geçer.
    if os.path.exists(KOTA_AYAR):
        try:
            with open(KOTA_AYAR, encoding='utf-8') as f:
                ayar = json.load(f)
            ayar['betik_esigi'] = yuzde
            if haftalik_yuzde is not None:
                ayar['haftalik_betik_esigi'] = haftalik_yuzde
            elif 'haftalik_betik_esigi' in ayar:
                del ayar['haftalik_betik_esigi']
            with open(KOTA_AYAR, 'w', encoding='utf-8') as f:
                json.dump(ayar, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    gorevi_yeniden_baslat()
    if haftalik_yuzde is not None:
        return 'Eşikler (5 saatlik: %%%d, haftalık: %%%d) kaydedildi, otomatik geçiş yeniden başlatıldı.' % (yuzde, haftalik_yuzde)
    return '5 saatlik eşik %%%d kaydedildi (haftalık sınır yok), otomatik geçiş yeniden başlatıldı.' % yuzde


EKLEME_LOG = os.path.join(KLASOR, 'ekleme.log')
EKLEME_SINIRI_SN = 30 * 60
ekleme_sureci = None


def agaci_kapat(pid):
    subprocess.run(['taskkill', '/T', '/F', '/PID', str(pid)], capture_output=True,
                   creationflags=CREATE_NO_WINDOW)


def asili_girisleri_kapat():
    # Önceki bir eklemeden yetim kalmış "claude auth login" yeni girişle aynı anda
    # giriş dosyasına yazardı. Yalnız komut satırında "auth login" olanlar kapanır;
    # çalışan Claude Code oturumlarına dokunulmaz.
    subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                    "Get-CimInstance Win32_Process -Filter \"Name='claude.exe'\" | "
                    "Where-Object { $_.CommandLine -match ' auth login' } | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                   capture_output=True, creationflags=CREATE_NO_WINDOW)


def ekleme_adimi():
    """hesap-ekle.ps1'in en son anlamlı satırı: kişi pencerede ne beklendiğini görsün."""
    for s in reversed(kuyruk(EKLEME_LOG, 20_000)):
        s = s.strip()
        if s.startswith('>>>'):
            return s.lstrip('> ').replace(' : ', ': ')
        if s.startswith(('Giriş ', 'Added Account', 'Updated credentials', 'EKLENEMEYENLER')) or s.endswith('atlandı.'):
            return s
    return ''


def ekle(govde):
    global ekleme_sureci
    eposta = str(govde.get('eposta') or '').strip()
    if not EPOSTA.match(eposta):
        raise ValueError('Geçerli bir e-posta yaz: ör. ornek@sirket.com')
    with kilit:
        if ekleme.get('durum') == 'suruyor':
            raise ValueError('%s için giriş sürüyor. Bitmesini bekle ya da İptal de.' % ekleme['eposta'])
        ekleme.clear()
        ekleme.update(eposta=eposta, durum='suruyor', basladi=time.time(),
                      mesaj='Tarayıcıda claude.ai\'a %s ile gir, sonra açılan kutuda Tamam\'a bas.' % eposta)
    asili_girisleri_kapat()
    # Çıktı boruya değil dosyaya: boruyu miras alan bir alt süreç (claude auth login)
    # askıda kalınca okuma hiç bitmiyor, ekleme sonsuza kadar "sürüyor" görünüyordu.
    cikti = open(EKLEME_LOG, 'w', encoding='utf-8')
    ekleme_sureci = subprocess.Popen(
        ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', HESAP_EKLE, eposta],
        stdin=subprocess.DEVNULL, stdout=cikti, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
    surec = ekleme_sureci

    def bekle():
        try:
            try:
                kod = surec.wait(timeout=EKLEME_SINIRI_SN)
            except subprocess.TimeoutExpired:
                agaci_kapat(surec.pid)
                kod = 'süre doldu'
            cikti.close()
            with open(EKLEME_LOG, encoding='utf-8', errors='replace') as f:
                metin = f.read()
            log('hesap-ekle %s -> %s\n%s' % (eposta, kod, metin))
            # Yeni hesapta "Added Account N", kayıtlıda "Updated credentials for Account N" yazar.
            eklendi = re.search(r'Added Account|Updated credentials for Account', metin)
            if eklendi:
                gorevi_yeniden_baslat()
            with kilit:
                if ekleme.get('durum') != 'suruyor':
                    return  # İptal edildi; mesajı iptal yazdı.
                ekleme.update(durum='bitti' if eklendi else 'olmadi',
                              mesaj=('%s kaydedildi, otomatik geçiş onu da görüyor.' % eposta) if eklendi else
                              ('%s eklenemedi. %s' % (eposta, ekleme_adimi() or 'Kutuda İptal denildi ya da giriş tamamlanmadı.')))
        except Exception as e:
            log('hesap-ekle hatasi: ' + traceback.format_exc())
            with kilit:
                ekleme.update(durum='olmadi', mesaj='%s eklenemedi: %s' % (eposta, e))

    threading.Thread(target=bekle, daemon=True).start()
    return ekleme['mesaj']


def ekle_iptal(_):
    with kilit:
        if ekleme.get('durum') != 'suruyor':
            raise ValueError('Süren bir hesap ekleme yok.')
        ekleme.update(durum='olmadi', mesaj='%s için giriş iptal edildi.' % ekleme['eposta'])
    if ekleme_sureci and ekleme_sureci.poll() is None:
        agaci_kapat(ekleme_sureci.pid)
    asili_girisleri_kapat()
    return 'Giriş iptal edildi.'


def sil(govde):
    no = no_al(govde)
    hesap = next((a for a in cswap_liste(taze=True)['accounts'] if a['number'] == no), None)
    if not hesap:
        raise ValueError('Bu numarada hesap yok.')
    if hesap.get('active'):
        # Aktif hesabı listeden silmek Claude Code'u o hesapta, ama takipsiz bırakırdı:
        # eşikte geçiş olmaz. Önce başka hesaba geçilsin.
        raise ValueError('%s şu an aktif. Önce başka bir hesaba geç, sonra sil.' % ad(hesap['email']))
    # cswap remove onay soruyor ("[y/N]"); --yes seçeneği yok, cevap girdiden verilir.
    r = subprocess.run([CSWAP, 'remove', str(no)], input='y\n', capture_output=True, text=True,
                       encoding='utf-8', errors='replace', env=ORTAM, creationflags=CREATE_NO_WINDOW,
                       timeout=60)
    if 'Removed' not in r.stdout:
        raise RuntimeError('Silinemedi: ' + ilk_satir(r.stderr, r.stdout))
    gorevi_yeniden_baslat()
    return '%s silindi. Geri eklemek için Hesap ekle\'den yeniden giriş gerekir.' % ad(hesap['email'])


def kapandi(_):
    # Pencere kapanıyor: başka pencere yoklamazsa sunucu KAPANDI_BEKLE_SN sonra kapanır.
    # Yenilenen sayfa hemen yokladığı için yenilemede kapanmaz.
    global son_istek
    son_istek = time.time() - BOSTA_KAPAN_SN + KAPANDI_BEKLE_SN
    return 'Tamam.'


# Sıfırlama hakkı (limit reset): Anthropic hesaplara ara sıra verir; claude.ai'de (ve masaüstü
# uygulamasında) Ayarlar → Kullanım → "Limit resets" → "Reset for free" ile kullanılır, Claude Code
# terminalinde yok (support.claude.com/en/articles/17007452). Tıklamayı kişi yapar: pencere yalnız
# doğru hesabın Kullanım sayfasını açar. claude.ai'nin girişi Claude Code'unkinden ayrı; her hesap
# kendi tarayıcı profilinde açılır, ilk seferde bir kez girilir, sonra girili kalır. Ana tarayıcıda
# çıkış-giriş gerekmez, hesaplar birbirinin oturumunu bozmaz.
CLAUDE_AI_KULLANIM = 'https://claude.ai/settings/usage'
TARAYICI_PROFILLERI = os.path.join(os.environ.get('LOCALAPPDATA') or KLASOR, 'claude-account-switcher', 'tarayici')
sira = {'durum': None}  # dolu hesaplarda sırayla: durum, hesaplar, simdiki, sira_no, iptal


def profil_yolu(eposta):
    # Klasör numaradan değil e-postadan: cswap swap/move numaraları değiştirebilir.
    return os.path.join(TARAYICI_PROFILLERI, re.sub(r'[^A-Za-z0-9]+', '_', eposta))


def kullanim_sayfasi_ac(eposta):
    """Hesabın kendi tarayıcı profilinde claude.ai Kullanım sayfasını açar. (süreç, ilk kez mi) verir;
    tarayıcı yoksa (None, None)."""
    tarayici = next((t for t in TARAYICILAR if os.path.exists(t)), None)
    if not tarayici:
        webbrowser.open(CLAUDE_AI_KULLANIM)
        return None, None
    profil = profil_yolu(eposta)
    ilk_kez = not os.path.isdir(profil)
    p = subprocess.Popen([tarayici, '--user-data-dir=' + profil, '--no-first-run', '--no-default-browser-check',
                          '--window-size=1200,900', CLAUDE_AI_KULLANIM])
    return p, ilk_kez


def pencere_kapanana_kadar(p, eposta):
    """Ayrı profilin tarayıcısı pencere kapanınca biter. Profil zaten açıksa yeni süreç işi açık olana
    verip hemen çıkar; o zaman profilin kilidi kalkana kadar beklenir."""
    p.wait()
    kilit_dosyasi = os.path.join(profil_yolu(eposta), 'lockfile')
    while os.path.exists(kilit_dosyasi):
        try:
            os.remove(kilit_dosyasi)  # Tarayıcı açıkken silinemez; silindiyse tarayıcı kapanmıştır.
        except OSError:
            time.sleep(2)
            continue
        break


def claude_ai(govde):
    no = no_al(govde)
    hesap = next((a for a in cswap_liste()['accounts'] if a['number'] == no), None)
    if not hesap:
        raise ValueError('Bu numarada hesap yok.')
    p, ilk_kez = kullanim_sayfasi_ac(hesap['email'])
    if p is None:
        return ('Varsayılan tarayıcıda açıldı: orada %s ile girili olmalısın. Kullanım sayfasında '
                '"Limit resets" altındaki "Reset for free".' % hesap['email'])
    if ilk_kez:
        return ('%s için ayrı bir tarayıcı penceresi açıldı. İlk sefer: claude.ai\'a %s ile gir; sonra Kullanım '
                'sayfasında "Limit resets" altındaki "Reset for free". Bundan sonra bu pencere hep girili açılır.'
                % (ad(hesap['email']), hesap['email']))
    return '%s açıldı: "Limit resets" altındaki "Reset for free".' % ad(hesap['email'])


def sifirlanabilir(h, simdi_ts):
    """Sıfırlama hakkı bu hesapta işe yarar mı (arayuz.html'deki sifirlanabilir() ile aynı kural).
    Yalnız 5 saatlikte dolu: evet; 5 saatliği sıfırlayan hak hesabı hemen açar. Haftalıkta dolu:
    yalnız haftalığı 24 saatten uzaktaysa; 5 saatlik sıfırlama haftalık doluyken hesabı açmaz,
    birkaç saat sonra zaten yenilenecek hesaba da tam sıfırlama harcanmasın."""
    if h['durum'] not in ('aktif', 'dolu'):
        return False
    if h['haftalik_dolu']:
        return bool(h['haftalik_sifirlanma']) and \
            datetime.fromisoformat(h['haftalik_sifirlanma']).timestamp() > simdi_ts + 24 * 3600
    return bool(h['saatlik_dolu'])


def sira_adaylari():
    """Sıfırlamanın işe yaradığı dolu hesaplar, en geç açılacak olan önce: sıfırlama en çok orada kazandırır."""
    esik, haftalik_esik = esik_oku()
    simdi_ts = datetime.now(timezone.utc).timestamp()
    adaylar = [h for h in hesaplar(esik, haftalik_esik) if sifirlanabilir(h, simdi_ts)]
    adaylar.sort(key=lambda h: h['acilma'] or '', reverse=True)
    return adaylar


def sifirla_sira(_):
    if not any(os.path.exists(t) for t in TARAYICILAR):
        raise ValueError('Sırayla açmak için Chrome ya da Edge gerekiyor.')
    with kilit:
        if sira.get('durum') == 'suruyor':
            raise ValueError('Sıra zaten sürüyor.')
    adaylar = sira_adaylari()
    if not adaylar:
        raise ValueError('Sıfırlamanın işe yarayacağı dolu hesap yok.')
    with kilit:
        sira.clear()
        sira.update(durum='suruyor', hesaplar=[h['ad'] for h in adaylar], simdiki=None, sira_no=0, iptal=False)

    def calistir():
        try:
            for i, h in enumerate(adaylar, 1):
                with kilit:
                    if sira.get('iptal'):
                        break
                    sira.update(simdiki=h['ad'], sira_no=i)
                p, _ = kullanim_sayfasi_ac(h['eposta'])
                pencere_kapanana_kadar(p, h['eposta'])
            liste_bayat()
        except Exception:
            log('sirayla sifirlama hatasi: ' + traceback.format_exc())
        finally:
            with kilit:
                sira.update(durum='iptal' if sira.get('iptal') else 'bitti', simdiki=None)

    threading.Thread(target=calistir, daemon=True).start()
    return ('%d hesap sırayla açılacak. Her pencerede "Reset for free"a bas, sonra pencereyi kapat; '
            'sıradaki kendiliğinden açılır.' % len(adaylar))


def sifirla_iptal(_):
    with kilit:
        if sira.get('durum') != 'suruyor':
            raise ValueError('Süren bir sıra yok.')
        sira['iptal'] = True
    return 'Açık pencereyi kapatınca sıra duracak.'


# 5 saatlik pencereleri seçilen saatte başlatma. İşi pencere-baslat.pyw yapar (Görev Zamanlayıcı'daki
# "claude-pencere-baslat" görevi ya da "Şimdi başlat"); pencere saatleri kaydeder ve son durumu gösterir.
PENCERE_BETIK = os.path.join(KLASOR, 'pencere-baslat.pyw')
PENCERE_VERI = os.path.join(os.environ.get('LOCALAPPDATA') or KLASOR, 'claude-account-switcher')
PENCERE_AYAR = os.path.join(PENCERE_VERI, 'pencere-baslat.json')
PENCERE_DURUM = os.path.join(PENCERE_VERI, 'pencere-baslat.durum.json')
PENCERE_MUTEX = 'Local\\claude-account-switcher-pencere'
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def json_dosya(yol):
    try:
        with open(yol, encoding='utf-8') as f:
            veri = json.load(f)
        return veri if isinstance(veri, dict) else {}
    except (OSError, ValueError):
        return {}


def yorumlayici(konsolsuz):
    """Pencere pythonw ile açılır; betiğin çıktısını okumak için yanındaki python.exe gerekir."""
    yol = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe' if konsolsuz else 'python.exe')
    return yol if os.path.exists(yol) else sys.executable


def pencere_durumu():
    son = json_dosya(PENCERE_DURUM)
    calisiyor = mutex_var(PENCERE_MUTEX)
    if son.get('durum') == 'suruyor' and not calisiyor:
        son['durum'] = 'yarida'  # süreç bitirmeden kapandı (bilgisayar kapandı vb.)
    return {'saatler': json_dosya(PENCERE_AYAR).get('saatler') or [], 'calisiyor': calisiyor, 'son': son}


def saatleri_coz(metin):
    saatler = set()
    for parca in re.split(r'[\s,;]+', str(metin or '').strip()):
        if not parca:
            continue
        m = re.fullmatch(r'(\d{1,2})(?:[:.](\d{2}))?', parca)
        if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
            raise ValueError('"%s" saat değil: 08:00 gibi yaz, birden çoksa virgülle ayır.' % parca)
        saatler.add('%02d:%02d' % (int(m.group(1)), int(m.group(2) or 0)))
    if len(saatler) > 6:
        raise ValueError('En çok 6 saat yazılabilir.')
    return sorted(saatler)


def pencere_kaydet(govde):
    saatler = saatleri_coz(govde.get('saatler'))
    r = subprocess.run([yorumlayici(False), PENCERE_BETIK, '--saatler', *saatler], capture_output=True,
                       text=True, encoding='utf-8', errors='replace', env=ORTAM, cwd=KLASOR,
                       creationflags=CREATE_NO_WINDOW, timeout=90)
    if r.returncode != 0:
        raise RuntimeError(ilk_satir(r.stdout, r.stderr) or 'Kaydedilemedi (kod %s).' % r.returncode)
    if not saatler:
        return 'Saatler silindi: zamanlanmış başlatma kapandı. "Şimdi başlat" yine çalışır.'
    mesaj = 'Kaydedildi: her gün %s saatinde boştaki hesapların 5 saatlik penceresi başlar.' % ', '.join(saatler)
    # Arası 5 saatten kısa saatlerde ikinci tetikte, ilkinde başlayan pencereler hâlâ sürer.
    dakika = [int(s[:2]) * 60 + int(s[3:]) for s in saatler]
    araliklar = [b - a for a, b in zip(dakika, dakika[1:])] + ([dakika[0] + 1440 - dakika[-1]] if len(dakika) > 1 else [])
    if any(a < 300 for a in araliklar):
        mesaj += ' Not: arası 5 saatten kısa saatlerde, öncekinde başlayan hesaplar sürdüğü için atlanır.'
    return mesaj


def pencere_simdi(_):
    if mutex_var(PENCERE_MUTEX):
        raise ValueError('Başlatma zaten sürüyor.')
    komut = [yorumlayici(True), PENCERE_BETIK, '--simdi']
    # Pencere kapansa ya da yeni koda devretse de başlatma yarıda kalmasın: ayrı süreç.
    bayrak = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(komut, cwd=KLASOR, env=ORTAM, creationflags=bayrak | CREATE_BREAKAWAY_FROM_JOB)
    except OSError:
        subprocess.Popen(komut, cwd=KLASOR, env=ORTAM, creationflags=bayrak)
    for _ in range(20):  # sayfa ilk yoklamada "sürüyor" görsün
        if mutex_var(PENCERE_MUTEX):
            break
        time.sleep(0.25)
    return 'Başlatılıyor: boştaki her hesaba sırayla tek kısa mesaj gidiyor (hesap başına birkaç saniye).'


ISLEMLER = {'gec': gec, 'en-iyi': en_iyi, 'durdur': durdur, 'ac': ac, 'esik': esik_kaydet, 'ekle': ekle,
            'ekle-iptal': ekle_iptal, 'sil': sil, 'kapandi': kapandi, 'claude-ai': claude_ai,
            'sifirla-sira': sifirla_sira, 'sifirla-iptal': sifirla_iptal,
            'pencere-kaydet': pencere_kaydet, 'pencere-simdi': pencere_simdi}


class Isleyici(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def yanit(self, kod, govde, tur='application/json; charset=utf-8'):
        veri = govde if isinstance(govde, bytes) else json.dumps(govde, ensure_ascii=False).encode('utf-8')
        try:
            self.send_response(kod)
            self.send_header('Content-Type', tur)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(veri)))
            self.end_headers()
            self.wfile.write(veri)
        except OSError:
            pass  # Pencere yanıtı beklemeden kapandı (04.11 01:11 WinError 10053); hata değil.

    def yetkili(self):
        # Host denetimi DNS yeniden bağlama ile gelen isteği, anahtar başka sayfanın isteğini keser.
        port = self.server.server_address[1]
        if self.headers.get('Host') not in ('127.0.0.1:%d' % port, 'localhost:%d' % port):
            return False
        return secrets.compare_digest(self.headers.get('X-Anahtar', ''), ANAHTAR)

    def do_GET(self):
        global son_istek
        son_istek = time.time()
        yol = urlparse(self.path)
        if yol.path == '/':
            if parse_qs(yol.query).get('k', [''])[0] != ANAHTAR:
                return self.yanit(403, b'Kisayoldan ac.', 'text/plain; charset=utf-8')
            with open(SAYFA, 'rb') as f:
                return self.yanit(200, f.read(), 'text/html; charset=utf-8')
        if yol.path == '/api/durum':
            if not self.yetkili():
                return self.yanit(403, {'hata': 'Yetkisiz istek.'})
            try:
                return self.yanit(200, durum())
            except Exception as e:
                log('durum hatasi: ' + traceback.format_exc())
                return self.yanit(500, {'hata': str(e)})
        self.yanit(404, {'hata': 'Yok.'})

    def do_POST(self):
        global son_istek, islem_sayisi
        son_istek = time.time()
        islem = ISLEMLER.get(urlparse(self.path).path.removeprefix('/api/'))
        if not islem:
            return self.yanit(404, {'hata': 'Yok.'})
        if not self.yetkili():
            return self.yanit(403, {'hata': 'Yetkisiz istek.'})
        with kilit:
            islem_sayisi += 1
        try:
            uzunluk = int(self.headers.get('Content-Length') or 0)
            govde = json.loads(self.rfile.read(uzunluk) or b'{}') if uzunluk else {}
            return self.yanit(200, {'mesaj': islem(govde)})
        except ValueError as e:
            return self.yanit(400, {'hata': str(e)})
        except Exception as e:
            log('%s hatasi: %s' % (self.path, traceback.format_exc()))
            return self.yanit(500, {'hata': str(e)})
        finally:
            if islem is not kapandi:
                liste_bayat()  # geçiş/durdurma/silme listeyi değiştirdi; sonraki yoklama tazesini alsın
            with kilit:
                islem_sayisi -= 1


def pencere_ac(port, anahtar):
    adres = 'http://127.0.0.1:%d/?k=%s' % (port, anahtar)
    # Chrome ya da Edge'in uygulama penceresi: adres çubuğu ve sekme yok, ayrı pencere gibi durur.
    tarayici = next((t for t in TARAYICILAR if os.path.exists(t)), None)
    if tarayici:
        subprocess.Popen([tarayici, '--app=' + adres, '--window-size=1560,1000'])
    else:
        webbrowser.open(adres)


def kod_zamani():
    try:
        return os.path.getmtime(KAYNAK)
    except OSError:
        return None


calisan_kod = kod_zamani()


def kod_degisti():
    """Bu dosya değişti, 20 sn'dir dokunulmuyor (düzenleme bitti) ve derleniyor mu?"""
    zaman = kod_zamani()
    if zaman is None or zaman == calisan_kod or time.time() - zaman < 20:
        return False
    try:
        with open(KAYNAK, 'rb') as f:
            compile(f.read(), KAYNAK, 'exec')
        return True
    except (OSError, SyntaxError, ValueError):
        return False


def sunucu_kur(port):
    # Devirde eski süreç portu az önce bıraktı; bağlanamazsak yeni portla yeni pencere açılır.
    for _ in range(20 if port else 1):
        try:
            return ThreadingHTTPServer(('127.0.0.1', port), Isleyici)
        except OSError:
            time.sleep(0.5)
    return ThreadingHTTPServer(('127.0.0.1', 0), Isleyici)


def calis(sunucu):
    """Sunucuyu kapanana kadar çalıştırır: 'kapan' (pencere yok) ya da 'devret' (kod değişti)."""
    sonuc = ['kapan']

    def bekci():
        while True:
            time.sleep(15)
            with kilit:
                mesgul = ekleme.get('durum') == 'suruyor' or islem_sayisi > 0 or sira.get('durum') == 'suruyor'
            if mesgul:
                continue
            if time.time() - son_istek > BOSTA_KAPAN_SN:
                break
            if kod_degisti():
                sonuc[0] = 'devret'
                break
        sunucu.shutdown()

    threading.Thread(target=bekci, daemon=True).start()
    sunucu.serve_forever()
    return sonuc[0]


def devret(port):
    """Yeni kodu aynı port ve anahtarla başlatır; ayağa kalktıysa True."""
    try:
        yeni = subprocess.Popen([sys.executable, KAYNAK], cwd=KLASOR,
                                env=dict(os.environ, ARAYUZ_DEVIR='%d %s' % (port, ANAHTAR)))
    except OSError:
        log('devir baslatilamadi: ' + traceback.format_exc())
        return False
    son = time.time() + 30
    while time.time() < son and yeni.poll() is None:
        try:
            with open(ACIK_DOSYASI, encoding='utf-8') as f:
                if json.load(f).get('pid') == yeni.pid:
                    log('yeni kod devraldi (pid %d)' % yeni.pid)
                    return True
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    if yeni.poll() is None:
        agaci_kapat(yeni.pid)
    log('yeni kod ayaga kalkmadi (kod %s), eski kodla suruyor' % yeni.poll())
    return False


def main():
    global calisan_kod
    tek = k32.CreateMutexW(None, False, MUTEX)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        if DEVIR:
            return  # Arada başka bir kopya kalkmış; eski süreç bunu görüp kendisi sürer.
        # Zaten açık: yeni sunucu kurmadan aynı sunucuya bir pencere daha aç.
        try:
            with open(ACIK_DOSYASI, encoding='utf-8') as f:
                a = json.load(f)
            pencere_ac(a['port'], a['anahtar'])
        except Exception:
            log('acik pencere bulunamadi: ' + traceback.format_exc())
        return
    port = int(DEVIR[0]) if DEVIR else 0
    while True:
        sunucu = sunucu_kur(port)
        yeni_pencere = sunucu.server_address[1] != port
        port = sunucu.server_address[1]
        with open(ACIK_DOSYASI, 'w', encoding='utf-8') as f:
            json.dump({'port': port, 'anahtar': ANAHTAR, 'pid': os.getpid()}, f)
        if yeni_pencere:
            pencere_ac(port, ANAHTAR)
        sonuc = calis(sunucu)
        sunucu.server_close()
        if sonuc == 'kapan':
            try:
                os.remove(ACIK_DOSYASI)
            except OSError:
                pass
            return
        k32.CloseHandle(tek)
        if devret(port):
            return
        # Yeni kod kalkmadı: aynı portta eski kodla sürülür, aynı sürüm için yeniden denenmez.
        tek = k32.CreateMutexW(None, False, MUTEX)
        calisan_kod = kod_zamani()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log('arayuz hatasi: ' + traceback.format_exc())
        raise
