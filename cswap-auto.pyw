"""cswap auto'yu penceresiz ve tek kopya çalıştırır; durursa 30 sn sonra yeniden başlatır.

Görev Zamanlayıcı'daki "cswap-auto" görevi oturum açılışında bunu pythonw ile başlatır.
Önceki sürüm "powershell -WindowStyle Hidden" + Add-Content idi: Windows Terminal
varsayılan konsolken pencere gizlenmedi, Add-Content de günlüğü okuyan başka bir
program varken yazamayıp ekrana "dosya kullanımda" hatası bastı (27.10.2026).
Burada günlük tek tutamakla, paylaşımlı açılır; okuyan kimse yazmayı engellemez.
"""
import ctypes
import os
import subprocess
import time
import traceback

KLASOR = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(KLASOR, 'cswap-auto.log')
CSWAP = os.path.expanduser(r'~\.local\bin\cswap.exe')
CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.CreateMutexW.restype = ctypes.c_void_p
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


def yaz(f, metin):
    f.write(time.strftime('%Y-%m-%dT%H:%M:%S  ') + metin + '\n')
    f.flush()


def main():
    kilit = k32.CreateMutexW(None, False, 'Local\\claude-account-switcher-auto')
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return
    is_nesnesi = alt_surecler_benimle_olsun()
    ortam = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1')
    son_ekleme = 0.0
    while True:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 5 * 1024 * 1024:
            os.replace(LOG, LOG + '.old')
        bekleme = 30
        with open(LOG, 'a', encoding='utf-8') as f:
            yaz(f, 'cswap auto basliyor')
            p = subprocess.Popen([CSWAP, 'auto'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, env=ortam, creationflags=CREATE_NO_WINDOW,
                                 text=True, encoding='utf-8', errors='replace')
            for satir in p.stdout:
                yaz(f, satir.rstrip())
                # Elle /login ile listede olmayan bir hesaba girilince cswap auto yalnız
                # "unmanaged-active-account" deyip geçişi bırakıyordu (28.10 12:36–13:51,
                # 75 dakika hiç geçiş yok). Aktif giriş listeye kendiliğinden eklenir.
                if 'unmanaged-active-account' in satir and time.time() - son_ekleme > 300:
                    son_ekleme = time.time()
                    r = subprocess.run([CSWAP, 'add'], capture_output=True, text=True, encoding='utf-8',
                                       errors='replace', env=ortam, creationflags=CREATE_NO_WINDOW, timeout=120)
                    yaz(f, 'listede olmayan aktif hesap eklendi: %s' % ' '.join((r.stdout + r.stderr).split())[:200])
                    if 'Added Account' in r.stdout:
                        # Hesap listesi cswap auto başlarken okunuyor; yeni listeyle hemen yeniden başlasın.
                        # Yalnız başlatıcıyı öldürmek yetmez, Python alt süreci boruyu tutmaya devam eder.
                        subprocess.run(['taskkill', '/T', '/F', '/PID', str(p.pid)], capture_output=True,
                                       creationflags=CREATE_NO_WINDOW)
                        bekleme = 3
            yaz(f, 'cswap auto durdu (kod %s), %d sn sonra yeniden' % (p.wait(), bekleme))
        time.sleep(bekleme)
    return kilit, is_nesnesi


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # pythonw'nun konsolu yok; hata günlükte görünsün, görev de 30 sn sonra
        # yeniden başlamasa bile sebebi okunabilsin.
        with open(LOG, 'a', encoding='utf-8') as f:
            yaz(f, 'cswap-auto.pyw hatasi:\n' + traceback.format_exc())
        raise
