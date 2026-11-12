"""Durum satırındaki anlık kullanımı claude-swap'a aktarır; aktif hesap eşikteyse hemen geçer.

cswap auto kullanımı Anthropic'ten en sık dakikada bir okuyabiliyor (hesap başına saatte ~30
istek sınırı). Çok oturum açıkken hesap dakikada 15-35 puan eriyebiliyor (11.11: bir hesap
2 dakikada %0'dan %36'ya, bir başkası bir dakikada %65'ten %100'e): dakikalık okuma hem
pencerede geç görünüyor hem de eşiği kaçırıp hesabı %100'e dayatıyor, iş yarıda kalıyordu.
Claude Code ise durum satırına her yanıtta güncel yüzdeyi veriyor.

  esikte-gec.py --aktar '<json>'   durum satırından: okumayı claude-swap'a aktar, aktif hesap
                                   eşikteyse geç. json: {"five_hour": {"used_percentage",
                                   "resets_at"}, "seven_day": {...}, "zaman": unix}
  esikte-gec.py --limit            StopFailure hook'u (rate_limit): oturum sınıra çarptı, hemen geç
  esikte-gec.py                    eski çağrı (KOTA_PENCERE/KOTA_YUZDE/KOTA_SIFIRLANMA_UNIX ortamı)
  esikte-gec.py --deneme ['<json>']  hiçbir şey yazmadan ne yapacağını göster

Eskiden "cswap switch --strategy best" çağrılıyordu. O da aktif hesabın yüzdesini kendi eski
kaydından okuyup (durum satırı %83 derken kayıt %0) "zaten en iyi hesaptasın" diyordu: 9-11.11
arasında 53 tetikten 17'si böyle boşa gitti. Artık aktif hesap adaylardan çıkarılır, hedef
burada, durum satırının yüzdesiyle seçilir.

Okuma hangi hesabın? Durum satırı, oturumun son yanıtı hangi hesaptan geldiyse onun kullanımını
gösterir; geçişten sonra bir süre eski hesabın yüzdesini çizen oturumlar olur. Okumanın 5 saatlik
ve haftalık sıfırlanma saatleri kayıtla karşılaştırılır: aktif hesapla çelişen ya da başka bir
hesapla eşleşen okuma aktif hesaba yazılmaz, ona göre geçiş yapılmaz. Aynı penceredeki yüzde
yalnız artar: kayıttan düşük okuma eski bir oturumdandır, aktarılmaz.

Fable sınırı ve öncelik sırası (gecis_politika.py; ayar: %LOCALAPPDATA%\\claude-account-switcher\\gecis-ayar.json,
panelden değiştirilir): Fable sınırı varsa aktif hesabın Fable yüzdesi (durum satırında yok, cswap deposundan,
okuma sıklığı kadar gecikmeli) sınıra gelince de geçilir ve hedef seçerken Fable'ı sınırda olan hesap elenir.
Öncelik açıksa hedef "en boş" yerine listedeki ilk uygun hesaptır. Ayar okunamazsa eski davranış sürer.
"""
import ctypes
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

KLASOR = os.path.dirname(os.path.abspath(__file__))
if KLASOR not in sys.path:  # durum satırı betiği tam yolla çağırıyor: yanındaki modüller bulunsun
    sys.path.insert(0, KLASOR)
import gecis_politika  # noqa: E402  Fable sınırı, öncelik sırası ve hedef seçimi
from gecis_politika import hedef_sec, kayit  # noqa: E402,F401  (kayit: uyum/yeni_kullanim da kullanıyor)

CSWAP = os.path.expanduser(r'~\.local\bin\cswap.exe')
CSWAP_AYAR = os.path.expanduser(r'~\.claude-swap-backup\settings.json')
CSWAP_OTO = os.path.expanduser(r'~\.claude-swap-backup\autoswitch_state.json')
GECIS_LOG = os.path.join(KLASOR, 'gecisler.log')
DURUM = os.path.join(KLASOR, 'anlik.json')  # son geçiş zamanı, "boş hesap yok" notu
# Çıktı bir günlüğe yönlenebiliyor; UTF-8 zorlanmazsa cswap'in ├ ve İ harfleri
# yerel kod sayfasına yazılamayıp geçiş yarıda patlardı.
ORTAM = dict(os.environ, PYTHONUTF8='1')
CREATE_NO_WINDOW = 0x08000000
MUTEX = 'Local\\claude-account-switcher-anlik'
PENCERELER = (('five_hour', 'fiveHour'), ('seven_day', 'sevenDay'))
# Sıfırlanma saatleri 10 dakikaya yuvarlı geliyor; ayrı hesapların pencereleri 10 dk arayla
# bitebiliyor. 5 dakikadan yakınsa aynı pencere sayılır.
AYNI_SN = 5 * 60
# Aynı anda sınıra çarpan birkaç oturum art arda geçiş yaptırmasın; geçişten önce yola çıkmış
# bir isteğin sınır hatası da yeni hesaptan geri geçirmesin.
LIMIT_ARALIK_SN = 90

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.CreateMutexW.restype = ctypes.c_void_p
k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
k32.ReleaseMutex.argtypes = [ctypes.c_void_p]


def yaz(metin):
    if sys.stdout:
        try:
            print(metin, flush=True)
        except OSError:
            pass


def json_oku(yol):
    try:
        with open(yol, encoding='utf-8') as f:
            veri = json.load(f)
        return veri if isinstance(veri, dict) else {}
    except (OSError, ValueError):
        return {}


def json_yaz(yol, veri):
    gecici = '%s.%d.tmp' % (yol, os.getpid())
    try:
        with open(gecici, 'w', encoding='utf-8') as f:
            json.dump(veri, f)
        os.replace(gecici, yol)
    except OSError:
        try:
            os.remove(gecici)
        except OSError:
            pass


def cswap(*arg, girdi=None, zaman=60):
    r = subprocess.run([CSWAP, *arg], input=girdi, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=ORTAM, creationflags=CREATE_NO_WINDOW, timeout=zaman)
    ilk = next((s.strip() for s in (r.stdout + '\n' + r.stderr).splitlines() if s.strip()), '')
    return r.returncode, r.stdout, ilk


def esikler():
    ayar = json_oku(CSWAP_AYAR).get('autoswitch') or {}
    saatlik = float(ayar['threshold']) if ayar.get('threshold') is not None else 90.0
    haftalik = float(ayar['weeklyThreshold']) if ayar.get('weeklyThreshold') is not None else saatlik
    return saatlik, haftalik


def uyum(okuma, satir, simdi):
    """Okuma bu hesabın olabilir mi: çelişirse None, yoksa sıfırlanma saati eşleşen pencere sayısı."""
    eslesen = 0
    for ok, ka in PENCERELER:
        r = (okuma.get(ok) or {}).get('resets_at')
        _, kr = kayit(satir, ka, simdi)
        if r is None or kr is None:
            continue
        if abs(kr - r) > AYNI_SN:
            return None
        eslesen += 1
    return eslesen


def sahibi(okuma, hesaplar, aktif, simdi):
    """Okumanın ait olduğu hesap satırı; kestirilemezse None."""
    ua = uyum(okuma, aktif, simdi) if aktif else None
    if ua:
        return aktif
    digerleri = [(u, s) for s in hesaplar if s is not aktif for u in [uyum(okuma, s, simdi)] if u]
    if digerleri:
        en_cok = max(u for u, _ in digerleri)
        tepe = [s for u, s in digerleri if u == en_cok]
        return tepe[0] if len(tepe) == 1 else None
    # Hiçbir hesapla eşleşmiyor ama aktifle çelişmiyor: aktif hesabın penceresi kayıttan sonra başlamış.
    return aktif if ua == 0 else None


def yeni_kullanim(satir, okuma, simdi):
    """Okumayı kayda işlenmiş kullanım; değişen yoksa None. Yüzde aynı pencerede yalnız artar."""
    usage = json.loads(json.dumps(satir.get('usage') or {}))
    degisti = False
    for ok, ka in PENCERELER:
        o = okuma.get(ok) or {}
        if o.get('used_percentage') is None:
            continue
        pct, r = float(o['used_percentage']), o.get('resets_at')
        if r is not None and r <= simdi:
            continue  # bitmiş pencereye ait
        eski_pct, eski_r = kayit(satir, ka, simdi)
        if eski_r is not None and r is not None:
            if r < eski_r - AYNI_SN:
                continue  # kayıttakinden eski bir pencere
            if abs(r - eski_r) <= AYNI_SN and eski_pct is not None and pct <= eski_pct:
                continue  # aynı pencere, kayıt zaten bu kadar ya da daha yüksek
        w = dict(usage.get(ka) or {})
        w['pct'] = pct
        if r is not None:
            w['resetsAt'] = datetime.fromtimestamp(r, timezone.utc).isoformat()
        usage[ka] = w
        degisti = True
    return usage if degisti else None


def aktar(veri, satir, usage, yas):
    """claude-swap'ın kullanım deposuna yaz (cswap import-usage: kayıttakinden yeniyse alır)."""
    belge = {'schemaVersion': veri.get('schemaVersion'), 'accounts': [{
        'email': satir['email'], 'organizationUuid': satir.get('organizationUuid') or '',
        'usageStatus': 'ok', 'usageAgeSeconds': max(0.0, float(yas)), 'usage': usage}]}
    kod, _, ilk = cswap('import-usage', '-', girdi=json.dumps(belge))
    return kod == 0, ilk


def son_gecis_zamani():
    """Bizim, cswap auto'nun ya da pencerenin son geçişi (unix)."""
    zamanlar = [json_oku(DURUM).get('zaman') or 0, json_oku(CSWAP_OTO).get('lastSwitchAt') or 0]
    try:
        with open(GECIS_LOG, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4000))
            for s in f.read().decode('utf-8', 'replace').splitlines():
                if 'Switched to' in s:
                    try:
                        zamanlar.append(time.mktime(time.strptime(s[:19], '%Y-%m-%d %H:%M:%S')))
                    except ValueError:
                        pass
    except OSError:
        pass
    return max(zamanlar)


def gecis_yaz(satir):
    yaz(satir)
    try:
        with open(GECIS_LOG, 'a', encoding='utf-8') as f:
            f.write(satir + '\n')
    except OSError:
        pass


def politika():
    """(Fable sınırı, öncelik listesi). Ayar okunamazsa geçişi kırmasın: eski davranış (Fable yok, öncelik yok)."""
    try:
        ayar = gecis_politika.ayar_oku()
        return ayar['fable_esigi'], (ayar['oncelik'] if ayar['oncelik_acik'] else None)
    except Exception:
        return None, None


def gec(hesaplar, aktif, simdi, neden, deneme, aktif_yuzde=None):
    esik, h_esik = esikler()
    fable_esik, oncelik = politika()
    hedef = hedef_sec(hesaplar, aktif, simdi, esik, h_esik, aktif_yuzde, fable_esik, oncelik)
    zaman = time.strftime('%Y-%m-%d %H:%M:%S ')
    durum = json_oku(DURUM)
    if hedef is None:
        # Her yanıtta tekrar yazılmasın: aktif hesap başına bir kez.
        not_ = str(aktif.get('number') if aktif else '?')
        if deneme:
            yaz('geçilecek boş hesap yok')
        elif durum.get('bos_yok') != not_:
            durum['bos_yok'] = not_
            json_yaz(DURUM, durum)
            gecis_yaz(zaman + 'cswap switch (%s): geçilecek boş hesap yok, en erken sıfırlanan bekleniyor' % neden)
        return
    if deneme:
        yaz('geçilecek: Account-%s (%s)' % (hedef['number'], hedef['email']))
        return
    kod, _, ilk = cswap('switch', str(hedef['number']))
    durum.update(zaman=time.time(), bos_yok=None)
    json_yaz(DURUM, durum)
    gecis_yaz(zaman + 'cswap switch (kod %d, %s): %s' % (kod, neden, ilk))


def kilitle():
    """Aynı anda tek kopya: her yanıtta tetiklenen kopyalar sırayla, güncel kayıtla çalışsın."""
    kilit = k32.CreateMutexW(None, False, MUTEX)
    if kilit and k32.WaitForSingleObject(kilit, 20000) in (0, 0x80):  # WAIT_OBJECT_0, WAIT_ABANDONED
        return kilit
    return None


def okuma_ortamdan():
    pencere = os.environ.get('KOTA_PENCERE') or 'five_hour'
    try:
        yuzde = float(os.environ['KOTA_YUZDE'].split()[0])
    except (KeyError, ValueError, IndexError):
        return None
    try:
        sif = float(os.environ.get('KOTA_SIFIRLANMA_UNIX') or '') or None
    except ValueError:
        sif = None
    return {pencere: {'used_percentage': yuzde, 'resets_at': sif}, 'zaman': time.time()}


def main():
    sys.stdout and sys.stdout.reconfigure(encoding='utf-8')
    arg = sys.argv[1:]
    deneme = '--deneme' in arg
    arg = [a for a in arg if a != '--deneme']
    limit = arg[:1] == ['--limit']
    okuma = None
    if arg[:1] == ['--aktar']:
        arg = arg[1:]
    if not limit:
        try:
            okuma = json.loads(arg[0]) if arg else okuma_ortamdan()
        except ValueError:
            okuma = None
        if not isinstance(okuma, dict):
            if not deneme:
                return 2
            limit = True  # --deneme tek başına: aktif hesaptan nereye geçileceğini göster

    kilit = kilitle()
    try:
        simdi = time.time()
        if limit and simdi - son_gecis_zamani() < LIMIT_ARALIK_SN:
            yaz('az önce geçildi; bu sınır hatası önceki hesaptan')
            return 0
        kod, cikti, ilk = cswap('list', '--json')
        try:
            veri = json.loads(cikti)
            hesaplar = veri['accounts']
        except (ValueError, KeyError, TypeError):
            yaz('hesap listesi okunamadı: ' + ilk)
            return 1
        aktif = next((s for s in hesaplar if s.get('active')), None)

        if limit:
            gec(hesaplar, aktif, simdi, 'sınır hatası', deneme, aktif_yuzde=100.0)
            return 0

        sahip = sahibi(okuma, hesaplar, aktif, simdi)
        if sahip is None:
            if deneme:  # her yanıtta çalışıyor; günlüğü doldurmasın
                yaz('okuma hiçbir hesapla kesin eşleşmedi; aktarılmadı')
            return 0
        usage = yeni_kullanim(sahip, okuma, simdi)
        if usage is not None:
            if deneme:
                yaz('aktarılacak: Account-%s %s' % (sahip['number'], json.dumps(
                    {k: usage.get(k, {}).get('pct') for _, k in PENCERELER})))
            else:
                tamam, ilk = aktar(veri, sahip, usage, simdi - float(okuma.get('zaman') or simdi))
                if not tamam:
                    yaz('aktarılamadı: ' + ilk)
        if sahip is not aktif:
            return 0  # eski hesapta kalmış bir oturumun okuması: geçiş kararı bundan verilmez
        esik, h_esik = esikler()
        p5 = (okuma.get('five_hour') or {}).get('used_percentage')
        p7 = (okuma.get('seven_day') or {}).get('used_percentage')
        # Fable durum satırında yok: kayıttan (cswap deposu) okunur, cswap'ın okuma sıklığı kadar gecikmeli olabilir.
        fable_esik = politika()[0]
        pf = gecis_politika.fable_yuzde(aktif, simdi) if aktif else None
        if p5 is not None and p5 >= esik:
            gec(hesaplar, aktif, simdi, 'kota %%%d' % p5, deneme)
        elif p7 is not None and p7 >= h_esik:
            gec(hesaplar, aktif, simdi, 'kota %%%d hafta' % p7, deneme)
        elif fable_esik is not None and pf is not None and pf >= fable_esik:
            gec(hesaplar, aktif, simdi, 'Fable %%%d' % pf, deneme)  # aktif_yuzde yok: yedek dal kapalı, döngü olmaz
        elif deneme:
            yaz('eşiğin altında (5 saat %s, hafta %s, Fable %s)' % (p5, p7, None if pf is None else int(round(pf))))
        return 0
    finally:
        if kilit:
            k32.ReleaseMutex(kilit)


if __name__ == '__main__':
    sys.exit(main())
