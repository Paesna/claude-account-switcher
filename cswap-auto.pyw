"""cswap auto'yu penceresiz ve tek kopya çalıştırır; durursa ya da takılırsa yeniden başlatır.

Görev Zamanlayıcı'daki "cswap-auto" görevi oturum açılışında ve 5 dakikada bir bunu
pythonw ile başlatır (çalışıyorsa yeni tetik yok sayılır, mutex de ikinci kopyayı keser).
Önceki sürüm "powershell -WindowStyle Hidden" + Add-Content idi: Windows Terminal
varsayılan konsolken pencere gizlenmedi, Add-Content de günlüğü okuyan başka bir
program varken yazamayıp ekrana "dosya kullanımda" hatası bastı (27.10.2026).
Burada günlük tek tutamakla, paylaşımlı açılır; okuyan kimse yazmayı engellemez.

Gece boyu açık kalması için: hiçbir hata bu döngüyü bitirmez (günlüğe yazılır, 60 sn
sonra yeniden denenir); cswap auto 15 dakika tek satır yazmazsa takılmış sayılıp
yeniden başlatılır; günlük çalışırken de 5 MB'ta döner.
"""
import ctypes
import os
import subprocess
import threading
import time
import traceback

KLASOR = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(KLASOR, 'cswap-auto.log')
CSWAP = os.path.expanduser(r'~\.local\bin\cswap.exe')
CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183
LOG_SINIRI = 5 * 1024 * 1024
# cswap auto her turda (eşiğe yakınken 60 sn, uzaktayken 180 sn) en az bir satır yazar;
# en uzun sessizlik 07.11'de 7 dakikaydı. 15 dakika susarsa takılmıştır (dönmeyen bir
# ağ isteği vb.): öldürülüp yeniden başlatılır, geçiş gece boyu durmaz.
SESSIZLIK_SINIRI = 15 * 60

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.CreateMutexW.restype = ctypes.c_void_p
k32.CloseHandle.argtypes = [ctypes.c_void_p]
k32.CreateJobObjectW.restype = ctypes.c_void_p
k32.GetCurrentProcess.restype = ctypes.c_void_p
k32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]


class _Temel(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', ctypes.c_uint32), ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', ctypes.c_uint32),
                ('Affinity', ctypes.c_size_t), ('PriorityClass', ctypes.c_uint32),
                ('SchedulingClass', ctypes.c_uint32)]


class _Genis(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', _Temel), ('IoInfo', ctypes.c_uint64 * 6),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


def alt_surecler_benimle_olsun():
    """Görev durdurulunca cswap auto yetim kalıp ikinci bir kopyayla yarışmasın:
    bu süreç ve başlattıkları tek iş nesnesinde, tutamak kapanınca hepsi kapanır."""
    is_nesnesi = k32.CreateJobObjectW(None, None)
    bilgi = _Genis()
    bilgi.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k32.SetInformationJobObject(is_nesnesi, 9, ctypes.byref(bilgi), ctypes.sizeof(bilgi))
    k32.AssignProcessToJobObject(is_nesnesi, k32.GetCurrentProcess())
    return is_nesnesi


class Gunluk:
    """Tek tutamak, her satırda flush; 5 MB'ı geçince .old'a döner.

    Eskiden yalnız cswap auto yeniden başlarken dönüyordu: günlerce süren bir turda
    sınırsız büyüyordu, döndürme de pencere günlüğü okurken PermissionError verip
    bütün görevi düşürüyordu (görev de bir sonraki oturum açılışına kadar kalkmıyordu).
    Yazılamayan satır geçişi durdurmaz; döndürülemeyen günlük sonraki satırda yeniden denenir.
    """

    def __init__(self):
        self.f = None
        self.kilit = threading.Lock()

    def yaz(self, metin):
        with self.kilit:
            try:
                if self.f is None:
                    self.f = open(LOG, 'a', encoding='utf-8')
                self.f.write(time.strftime('%Y-%m-%dT%H:%M:%S  ') + metin + '\n')
                self.f.flush()
                if self.f.tell() > LOG_SINIRI:
                    self._kapat()
                    os.replace(LOG, LOG + '.old')
            except OSError:
                self._kapat()

    def _kapat(self):
        if self.f is not None:
            try:
                self.f.close()
            except OSError:
                pass
            self.f = None


def agaci_kapat(pid):
    subprocess.run(['taskkill', '/T', '/F', '/PID', str(pid)], capture_output=True,
                   creationflags=CREATE_NO_WINDOW)


def listeye_ekle(gunluk, ortam):
    """Elle /login ile girilen ve listede olmayan aktif hesabı listeye ekler; eklendiyse True."""
    try:
        r = subprocess.run([CSWAP, 'add'], capture_output=True, text=True, encoding='utf-8',
                           errors='replace', env=ortam, creationflags=CREATE_NO_WINDOW, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        gunluk.yaz('listede olmayan aktif hesap eklenemedi: %s' % e)
        return False
    gunluk.yaz('listede olmayan aktif hesap eklendi: %s' % ' '.join((r.stdout + r.stderr).split())[:200])
    return 'Added Account' in r.stdout


def bir_tur(gunluk, ortam, durum):
    """cswap auto'yu bir kez çalıştırır; bitince ya da takılınca döner. Sonraki beklemeyi verir."""
    gunluk.yaz('cswap auto basliyor')
    p = subprocess.Popen([CSWAP, 'auto'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, env=ortam, creationflags=CREATE_NO_WINDOW,
                         text=True, encoding='utf-8', errors='replace')
    son_satir = [time.monotonic()]
    bitti = threading.Event()

    def bekci():
        while not bitti.wait(min(30, SESSIZLIK_SINIRI / 4)):
            sessiz = time.monotonic() - son_satir[0]
            if sessiz > SESSIZLIK_SINIRI:
                gunluk.yaz('cswap auto %d dakikadir sessiz, takilmis sayilip yeniden baslatiliyor' % (sessiz // 60))
                agaci_kapat(p.pid)
                return

    threading.Thread(target=bekci, daemon=True).start()
    bekleme = 30
    try:
        for satir in p.stdout:
            son_satir[0] = time.monotonic()
            gunluk.yaz(satir.rstrip())
            # Elle /login ile listede olmayan bir hesaba girilince cswap auto yalnız
            # "unmanaged-active-account" deyip geçişi bırakıyordu (28.10 12:36–13:51,
            # 75 dakika hiç geçiş yok). Aktif giriş listeye kendiliğinden eklenir.
            if 'unmanaged-active-account' in satir and time.time() - durum['son_ekleme'] > 300:
                durum['son_ekleme'] = time.time()
                if listeye_ekle(gunluk, ortam):
                    # Hesap listesi cswap auto başlarken okunuyor; yeni listeyle hemen yeniden başlasın.
                    # Yalnız başlatıcıyı öldürmek yetmez, Python alt süreci boruyu tutmaya devam eder.
                    agaci_kapat(p.pid)
                    bekleme = 3
    finally:
        bitti.set()
        # Bir hata döngüyü yarıda kestiyse cswap auto arkada kalıp sonraki kopyayla yarışmasın.
        if p.poll() is None:
            agaci_kapat(p.pid)
    try:
        kod = p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        kod = '?'
    gunluk.yaz('cswap auto durdu (kod %s), %d sn sonra yeniden' % (kod, bekleme))
    return bekleme


def agy_oto_baslat(gunluk):
    """Gemini (agy) hesaplarının otomatik geçişi (agy_hesap.py): panelin Gemini sekmesinden açılıp kapanır, kapalıyken
    boşa iş yapmaz. Bu süreçte ayrı bir iş parçacığı: cswap auto'yu etkilemez; hata yalnız günlüğe yazılır."""
    try:
        import agy_hesap
    except Exception:
        gunluk.yaz('agy_hesap.py yuklenemedi, Gemini otomatik gecisi kapali:\n' + traceback.format_exc())
        return
    threading.Thread(target=agy_hesap.oto_dongu, args=(gunluk.yaz,), daemon=True, name='agy-oto').start()


def main():
    # Görev durdurulup hemen başlatılınca (kur.ps1, eşik kaydetme) eski kopya mutex'i birkaç
    # saniye daha tutabiliyor; yeni kopya "zaten çalışıyor" deyip çıkınca hiç kopya kalmıyordu
    # (08.11 01:23). 10 sn beklenir; o sürede bırakılmazsa gerçekten çalışan bir kopya vardır.
    for _ in range(20):
        kilit = k32.CreateMutexW(None, False, 'Local\\claude-account-switcher-auto')
        if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
            break
        k32.CloseHandle(kilit)
        time.sleep(0.5)
    else:
        return
    is_nesnesi = alt_surecler_benimle_olsun()
    ortam = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1')
    gunluk = Gunluk()
    durum = {'son_ekleme': 0.0}
    agy_oto_baslat(gunluk)
    while True:
        try:
            bekleme = bir_tur(gunluk, ortam, durum)
        except Exception:
            # cswap.exe yok (pipx güncellerken), disk dolu vb.: görev ölmesin, az sonra yeniden denesin.
            gunluk.yaz('cswap-auto.pyw hatasi, 60 sn sonra yeniden:\n' + traceback.format_exc())
            bekleme = 60
        time.sleep(bekleme)
    return kilit, is_nesnesi


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # pythonw'nun konsolu yok; hata günlükte görünsün. Görev 5 dakikada bir yeniden tetiklenir.
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%dT%H:%M:%S  ') + 'cswap-auto.pyw hatasi:\n' + traceback.format_exc() + '\n')
        raise
