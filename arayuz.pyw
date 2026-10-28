"""Claude hesapları penceresi: her hesabın kullanımı, sıfırlanma saati ve son geçişler;
tıklayarak hesaba geçme, hesabı durdurma/açma, eşiği kaydetme ve hesap ekleme.

Masaüstündeki "Claude hesapları" kısayolu bunu pythonw ile başlatır. Sayfa yalnız
127.0.0.1'den dinleyen bir sunucudan gelir ve Chrome'un uygulama penceresinde açılır.
Her açılışta rastgele bir anahtar üretilir; anahtarı başlıkta taşımayan istek reddedilir.
Yoksa tarayıcıda açık herhangi bir web sayfası yerel sunucuya istek atıp hesap
değiştirebilirdi. Pencere kapanınca sayfa yoklamayı bırakır, sunucu 3 dakika sonra kapanır.
"""
import ctypes
import json
import os
import re
import secrets
import subprocess
import threading
import time
import traceback
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

KLASOR = os.path.dirname(os.path.abspath(__file__))
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
BOSTA_KAPAN_SN = 180
EPOSTA = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.CreateMutexW.restype = ctypes.c_void_p
k32.OpenMutexW.restype = ctypes.c_void_p
k32.CloseHandle.argtypes = [ctypes.c_void_p]

ANAHTAR = secrets.token_urlsafe(24)
son_istek = time.time()
ekleme = {}          # sürmekte olan hesap ekleme: eposta, durum, mesaj
kilit = threading.Lock()


def log(metin):
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + metin + '\n')


def cswap(*arg, zaman=120):
    r = subprocess.run([CSWAP, *arg], capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=ORTAM, creationflags=CREATE_NO_WINDOW, timeout=zaman)
    return r.returncode, r.stdout, r.stderr


def ilk_satir(*metinler):
    return next((s.strip() for m in metinler for s in m.splitlines() if s.strip()), '')


def esik_oku():
    try:
        with open(CSWAP_AYAR, encoding='utf-8') as f:
            return int(round(json.load(f)['autoswitch']['threshold']))
    except Exception:
        return 90


def gorev_calisiyor():
    # cswap-auto.pyw tek kopyayı bu adlı mutex'le tutuyor; varsa görev ayakta.
    h = k32.OpenMutexW(0x00100000, False, 'Local\\claude-account-switcher-auto')
    if h:
        k32.CloseHandle(h)
        return True
    return False


def gorevi_yeniden_baslat():
    # cswap auto eşiği ve hesap listesini başlarken okuyor; yeni ayar ancak yeniden
    # başlayınca geçerli olur.
    for arg in (['/End'], ['/Run']):
        subprocess.run(['schtasks', *arg, '/TN', 'cswap-auto'], capture_output=True,
                       creationflags=CREATE_NO_WINDOW)
        time.sleep(2)


def ad(eposta):
    return eposta.split('@')[0]


def hesaplar(esik):
    kod, cikti, hata = cswap('list', '--json')
    # cswap bir hesabın kullanımı okunamayınca listeyi yine yazıp sıfırdan farklı kodla
    # bitebiliyor (28.10 11:52); JSON geldiyse onu kullan, gelmediyse hatayı göster.
    try:
        veri = json.loads(cikti)
    except ValueError:
        raise RuntimeError('Hesap listesi okunamadı (kod %s): %s' % (kod, ilk_satir(hata, cikti)))
    simdi = datetime.now(timezone.utc)
    satirlar = []
    for a in veri['accounts']:
        u = a.get('usage') or {}
        b, h = u.get('fiveHour'), u.get('sevenDay')
        yuzde = round(b['pct']) if b and b.get('pct') is not None else None
        sifir = None
        if b and b.get('resetsAt'):
            sifir = datetime.fromisoformat(b['resetsAt'])
            if sifir <= simdi:
                # Pencere sıfırlanmış, depo henüz tazelenmemiş: eski yüzde artık geçersiz.
                yuzde, sifir = 0, None
        if a.get('active'):
            durum = 'aktif'
        elif a.get('disabled'):
            durum = 'durduruldu'
        elif a.get('usageStatus') != 'ok' or yuzde is None:
            durum = 'okunamiyor'
        elif yuzde >= esik:
            durum = 'dolu'
        else:
            durum = 'hazir'
        satirlar.append({
            'no': a['number'], 'eposta': a['email'], 'ad': ad(a['email']),
            'kurum': a.get('organizationName') or '', 'durum': durum,
            'durduruldu': bool(a.get('disabled')), 'aktif': bool(a.get('active')),
            'yuzde': yuzde, 'sifirlanma': sifir.isoformat() if sifir else None,
            'haftalik': round(h['pct']) if h and h.get('pct') is not None else None,
            'hata': a.get('usageError') or '',
        })
    sira = {'aktif': 0, 'hazir': 1, 'dolu': 2, 'okunamiyor': 3, 'durduruldu': 4}
    satirlar.sort(key=lambda s: (sira[s['durum']],
                                 s['yuzde'] if s['durum'] == 'hazir' else 0,
                                 s['sifirlanma'] or '9999', s['no']))
    return satirlar


def kuyruk(yol, bayt=400_000):
    """Günlükler 5 MB'a kadar büyüyor; her yoklamada yalnız sonu okunur."""
    try:
        with open(yol, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - bayt))
            return f.read().decode('utf-8', errors='replace').splitlines()
    except OSError:
        return []


NEDEN = {'proactive': 'eşikte', 'at-limit': 'doldu'}


def gecisler(adlar):
    olaylar = []
    for s in kuyruk(AUTO_LOG):
        m = re.match(r'^(\S+)\s+\S+\s+Switched Account-(\d+) -> Account-(\d+) \(([^)]+)\)(?: \(([\w-]+)\))?', s)
        if m:
            olaylar.append({'zaman': m.group(1)[:19], 'kimden': adlar.get(int(m.group(2)), '#' + m.group(2)),
                            'kime': ad(m.group(4)), 'neden': NEDEN.get(m.group(5), m.group(5) or ''),
                            'tur': 'otomatik'})
        elif re.match(r'^\S+\s+\S+\s+all accounts exhausted', s):
            olaylar.append({'zaman': s[:19], 'tur': 'bekleme'})
    for yol in (GECIS_LOG, ESKI_OLAYLAR):
        son_saat = None
        for s in kuyruk(yol, 100_000):
            m = re.match(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ', s)
            if m:
                son_saat = m.group(1).replace(' ', 'T')
            m = re.search(r'cswap switch \((elle|[^)]*)\): Switched to Account-(\d+) \(([^)]+)\)', s)
            if m and son_saat:
                elle = m.group(1) == 'elle'
                olaylar.append({'zaman': son_saat, 'kime': ad(m.group(3)),
                                'neden': 'elle' if elle else 'hızlı tetik', 'tur': 'elle' if elle else 'hizli'})
    # Hızlı tetik geçişi hem kendi günlüğüne hem kota izleyicisinin günlüğüne düşebilir.
    olaylar = list({(o['zaman'], o.get('kime'), o['tur']): o for o in olaylar}.values())
    olaylar.sort(key=lambda o: o['zaman'], reverse=True)
    # "Hepsi dolu" her 10 dakikada bir yazılıyor; ardışık olanlardan yalnız ilki kalır.
    sonuc = []
    for o in olaylar:
        if o['tur'] == 'bekleme' and sonuc and sonuc[-1]['tur'] == 'bekleme':
            sonuc[-1] = o
            continue
        sonuc.append(o)
    return sonuc[:15]


def durum():
    esik = esik_oku()
    liste = hesaplar(esik)
    with kilit:
        ek = dict(ekleme)
    if ek.get('durum') == 'suruyor':
        ek['adim'] = ekleme_adimi()
        ek['sure_dk'] = int((time.time() - ek.get('basladi', time.time())) // 60)
    return {'esik': esik, 'gorev': gorev_calisiyor(), 'hesaplar': liste,
            'gecisler': gecisler({h['no']: h['ad'] for h in liste}), 'ekleme': ek,
            'saat': datetime.now().astimezone().isoformat()}


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
        raise ValueError('Eşik bir sayı olmalı.')
    if not 50 <= yuzde <= 99:
        raise ValueError('Eşik 50 ile 99 arasında olmalı.')
    kod, cikti, hata = cswap('config', 'set', 'autoswitch.threshold', str(yuzde))
    if kod != 0:
        raise RuntimeError('Kaydedilemedi: ' + ilk_satir(hata, cikti))
    # Durum satırındaki hızlı tetik (varsa) aynı eşikte çalışsın; ayrışırsa biri erken biri geç geçer.
    if os.path.exists(KOTA_AYAR):
        with open(KOTA_AYAR, encoding='utf-8') as f:
            ayar = json.load(f)
        ayar['betik_esigi'] = yuzde
        with open(KOTA_AYAR, 'w', encoding='utf-8') as f:
            json.dump(ayar, f, ensure_ascii=False, indent=2)
    gorevi_yeniden_baslat()
    return 'Eşik %%%d kaydedildi, otomatik geçiş yeniden başlatıldı.' % yuzde


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
    _, cikti, _ = cswap('list', '--json')
    hesap = next((a for a in json.loads(cikti)['accounts'] if a['number'] == no), None)
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


ISLEMLER = {'gec': gec, 'en-iyi': en_iyi, 'durdur': durdur, 'ac': ac, 'esik': esik_kaydet, 'ekle': ekle,
            'ekle-iptal': ekle_iptal, 'sil': sil}


class Isleyici(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def yanit(self, kod, govde, tur='application/json; charset=utf-8'):
        veri = govde if isinstance(govde, bytes) else json.dumps(govde, ensure_ascii=False).encode('utf-8')
        self.send_response(kod)
        self.send_header('Content-Type', tur)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(veri)))
        self.end_headers()
        self.wfile.write(veri)

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
        global son_istek
        son_istek = time.time()
        islem = ISLEMLER.get(urlparse(self.path).path.removeprefix('/api/'))
        if not islem:
            return self.yanit(404, {'hata': 'Yok.'})
        if not self.yetkili():
            return self.yanit(403, {'hata': 'Yetkisiz istek.'})
        try:
            uzunluk = int(self.headers.get('Content-Length') or 0)
            govde = json.loads(self.rfile.read(uzunluk) or b'{}') if uzunluk else {}
            return self.yanit(200, {'mesaj': islem(govde)})
        except ValueError as e:
            return self.yanit(400, {'hata': str(e)})
        except Exception as e:
            log('%s hatasi: %s' % (self.path, traceback.format_exc()))
            return self.yanit(500, {'hata': str(e)})


def pencere_ac(port, anahtar):
    adres = 'http://127.0.0.1:%d/?k=%s' % (port, anahtar)
    # Chrome ya da Edge'in uygulama penceresi: adres çubuğu ve sekme yok, ayrı pencere gibi durur.
    tarayici = next((t for t in TARAYICILAR if os.path.exists(t)), None)
    if tarayici:
        subprocess.Popen([tarayici, '--app=' + adres, '--window-size=1560,1000'])
    else:
        webbrowser.open(adres)


def main():
    tek = k32.CreateMutexW(None, False, 'Local\\claude-account-switcher-ui')
    if ctypes.get_last_error() == 183:
        # Zaten açık: yeni sunucu kurmadan aynı sunucuya bir pencere daha aç.
        try:
            with open(ACIK_DOSYASI, encoding='utf-8') as f:
                a = json.load(f)
            pencere_ac(a['port'], a['anahtar'])
        except Exception:
            log('acik pencere bulunamadi: ' + traceback.format_exc())
        return
    sunucu = ThreadingHTTPServer(('127.0.0.1', 0), Isleyici)
    port = sunucu.server_address[1]
    with open(ACIK_DOSYASI, 'w', encoding='utf-8') as f:
        json.dump({'port': port, 'anahtar': ANAHTAR}, f)

    def bekci():
        while True:
            time.sleep(15)
            with kilit:
                suruyor = ekleme.get('durum') == 'suruyor'
            if not suruyor and time.time() - son_istek > BOSTA_KAPAN_SN:
                sunucu.shutdown()
                return

    threading.Thread(target=bekci, daemon=True).start()
    pencere_ac(port, ANAHTAR)
    try:
        sunucu.serve_forever()
    finally:
        try:
            os.remove(ACIK_DOSYASI)
        except OSError:
            pass
    return tek


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log('arayuz hatasi: ' + traceback.format_exc())
        raise
