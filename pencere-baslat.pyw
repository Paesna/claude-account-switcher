"""Hesapların 5 saatlik pencerelerini seçilen saatte başlatır.

Anthropic'in 5 saatlik kullanım penceresi hesabın ilk mesajıyla başlar, 5 saat sonra sıfırlanır.
Seçilen saatte boşta olan (penceresi sürmeyen) her hesaba Claude Code'la tek kısa mesaj gider:
o hesabın penceresi o an başlar, 5 saat sonra sıfırlanır. Mesaj Haiku'ya, araçsız ve tek
cümlelik sistem istemiyle gider (~900 token, 11.11'de ölçüldü): kotadan neredeyse bir şey yemez.

Mesaj `cswap run <hesap>` ile gider: claude-swap hesabı kendi profilinde
(~/.claude-swap-backup/sessions) çalıştırır; aktif girişe, açık Claude Code oturumlarına ve
VS Code eklentisine dokunmaz, profilde yenilenen giriş anahtarını kendi yedeğine geri alır.
claude boş bir klasörde, kullanıcı ayarları yüklenmeden çalışır: hook'lar, durum satırı ve
MCP sunucuları devreye girmez (kota betiği hesap değiştirmesin).

Atlananlar: penceresi zaten süren (yeniden başlatılamaz), haftalıkta dolu (otomatik geçiş
zaten kullanmaz), durdurulan ve kullanımı okunamayan hesaplar.

  pencere-baslat.pyw                    Görev Zamanlayıcı'dan. Ayarlı saatten 30 dk'dan çok geç
                                        kalındıysa (bilgisayar o saatte kapalı ya da uykudaydı)
                                        çalışmaz: pencereler istenmeyen saate kaymasın.
  pencere-baslat.pyw --simdi            Pencereden "Şimdi başlat".
  pencere-baslat.pyw --saatler 08:00 …  Saatleri kaydeder, "claude-pencere-baslat" görevini kurar
                                        (saat verilmezse görevi kaldırır).
  pencere-baslat.pyw --kur              Kayıtlı saatlerle görevi yeniden kurar (kur.ps1, klasör taşınınca).
"""
import base64
import ctypes
import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

KLASOR = os.path.dirname(os.path.abspath(__file__))
BETIK = os.path.abspath(__file__)
LOG = os.path.join(KLASOR, 'pencere-baslat.log')
CSWAP = os.path.expanduser(r'~\.local\bin\cswap.exe')
CSWAP_AYAR = os.path.expanduser(r'~\.claude-swap-backup\settings.json')
VERI = os.path.join(os.environ.get('LOCALAPPDATA') or KLASOR, 'claude-account-switcher')
AYAR = os.path.join(VERI, 'pencere-baslat.json')
DURUM = os.path.join(VERI, 'pencere-baslat.durum.json')
# claude boş klasörde çalışır: bir projenin ayarı, CLAUDE.md'si ya da git durumu karışmasın.
BOS = os.path.join(VERI, 'bos')
GOREV = 'claude-pencere-baslat'
MUTEX = 'Local\\claude-account-switcher-pencere'
GEC_KALMA_SN = 30 * 60
HESAP_SURE_SN = 180
CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183
SAAT = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')

# Tek kısa mesaj: Haiku, araçsız, MCP'siz; kullanıcı ayarları (hook'lar, durum satırı) yüklenmez,
# oturum kaydı tutulmaz. Sistem istemi tek cümle olduğu için istek ~900 token.
CLAUDE_ARG = ['-p', 'ok', '--model', 'haiku', '--tools', '', '--strict-mcp-config',
              '--setting-sources', 'project', '--no-session-persistence',
              '--system-prompt', 'Reply with the single word: ok', '--output-format', 'json']
# Pencere bir Claude Code oturumundan açıldıysa bunlar alt claude'u o oturuma bağlar ya da girişi ezer.
TEMIZLE = ('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_CONFIG_DIR', 'CLAUDE_CODE_SSE_PORT',
           'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN')

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.CreateMutexW.restype = ctypes.c_void_p


def yaz(metin):
    """Konsol varsa (python.exe, --saatler) ekrana; pythonw'da stdout yok."""
    if sys.stdout:
        print(metin)


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


def json_oku(yol):
    try:
        with open(yol, encoding='utf-8') as f:
            veri = json.load(f)
        return veri if isinstance(veri, dict) else {}
    except (OSError, ValueError):
        return {}


def json_yaz(yol, veri):
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    gecici = yol + '.yeni'
    with open(gecici, 'w', encoding='utf-8') as f:
        json.dump(veri, f, ensure_ascii=False, indent=1)
    os.replace(gecici, yol)  # pencere yarım yazılmış dosya okumasın


def saatleri_oku():
    return [s for s in json_oku(AYAR).get('saatler') or [] if isinstance(s, str) and SAAT.match(s)]


def ad(eposta):
    return eposta.split('@')[0]


def ilk_satir(*metinler):
    return next((s.strip() for m in metinler for s in (m or '').splitlines() if s.strip()), '')


def esikler():
    saatlik, haftalik = 90, None
    ayar = json_oku(CSWAP_AYAR).get('autoswitch') or {}
    if ayar.get('threshold') is not None:
        saatlik = ayar['threshold']
    if ayar.get('weeklyThreshold') is not None:
        haftalik = ayar['weeklyThreshold']
    # Haftalık eşik boşsa cswap haftalıkta da 5 saatlik eşiği kullanıyor.
    return saatlik, haftalik if haftalik is not None else saatlik


def zaman(metin):
    try:
        return datetime.fromisoformat(metin) if metin else None
    except ValueError:
        return None


def sec(veri):
    """(başlatılacak [(ad, eposta)], atlanan [{ad, neden}])"""
    simdi = datetime.now(timezone.utc)
    _, haftalik_esik = esikler()
    secilen, atlanan = [], []
    for a in veri.get('accounts') or []:
        eposta = a.get('email') or ''
        u = a.get('usage') or {}
        b, h = u.get('fiveHour') or {}, u.get('sevenDay') or {}
        b_sifir, h_sifir = zaman(b.get('resetsAt')), zaman(h.get('resetsAt'))
        if a.get('disabled'):
            neden = 'durduruldu'
        elif a.get('usageStatus') != 'ok' or b.get('pct') is None:
            neden = 'kullanımı okunamıyor'
        elif b_sifir and b_sifir > simdi:
            neden = 'penceresi sürüyor'
        elif h.get('pct') is not None and h['pct'] >= haftalik_esik and h_sifir and h_sifir > simdi:
            neden = 'haftalıkta dolu'
        else:
            secilen.append((ad(eposta), eposta))
            continue
        atlanan.append({'ad': ad(eposta), 'neden': neden})
    return secilen, atlanan


def agaci_kapat(pid):
    subprocess.run(['taskkill', '/T', '/F', '/PID', str(pid)], capture_output=True, creationflags=CREATE_NO_WINDOW)


def baslat_bir(eposta):
    """Hesaba tek kısa mesaj; (başladı mı, hata metni)."""
    ortam = {k: v for k, v in os.environ.items() if k not in TEMIZLE}
    ortam['PYTHONUTF8'] = '1'
    os.makedirs(BOS, exist_ok=True)
    try:
        p = subprocess.Popen([CSWAP, 'run', eposta, '--no-share', '--', *CLAUDE_ARG], cwd=BOS, env=ortam,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding='utf-8', errors='replace', creationflags=CREATE_NO_WINDOW)
    except OSError as e:
        return False, str(e)
    try:
        cikti, hata = p.communicate(timeout=HESAP_SURE_SN)
    except subprocess.TimeoutExpired:
        agaci_kapat(p.pid)  # cswap kapansa da altındaki claude kalmasın
        p.communicate()
        return False, '%d sn içinde yanıt gelmedi' % HESAP_SURE_SN
    sonuc = None
    for satir in cikti.splitlines():
        satir = satir.strip()
        if satir.startswith('{'):
            try:
                j = json.loads(satir)
            except ValueError:
                continue
            if isinstance(j, dict) and j.get('type') == 'result':
                sonuc = j
    if sonuc and not sonuc.get('is_error'):
        return True, ''
    if sonuc:
        return False, str(sonuc.get('result') or sonuc.get('api_error_status') or sonuc.get('subtype'))[:200]
    return False, (ilk_satir(hata, cikti) or 'çıkış kodu %s' % p.returncode)[:200]


def cswap_liste():
    r = subprocess.run([CSWAP, 'list', '--json'], capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=dict(os.environ, PYTHONUTF8='1'),
                       creationflags=CREATE_NO_WINDOW, timeout=90)
    try:
        veri = json.loads(r.stdout)
    except ValueError:
        veri = None
    if not isinstance(veri, dict) or not isinstance(veri.get('accounts'), list):
        raise RuntimeError('Hesap listesi okunamadı: ' + ilk_satir(r.stderr, r.stdout))
    return veri


def son_ayarli_saat(saatler, simdi):
    """Şimdiden önceki en yakın ayarlı saat (dün olabilir)."""
    adaylar = []
    for s in saatler:
        sa, dk = map(int, s.split(':'))
        t = simdi.replace(hour=sa, minute=dk, second=0, microsecond=0)
        if t > simdi + timedelta(minutes=2):  # görev saniyeler önce tetiklenebilir
            t -= timedelta(days=1)
        adaylar.append(t)
    return max(adaylar, default=None)


def calistir(elle):
    simdi = datetime.now()
    if not elle:
        son = son_ayarli_saat(saatleri_oku(), simdi)
        if son is None or (simdi - son).total_seconds() > GEC_KALMA_SN:
            # Bilgisayar ayarlı saatte uykudaydı; görev uyanınca tetiklendi (StartWhenAvailable).
            # Saatler geçmişte kaldıysa pencereleri şimdi başlatmak onları istenmeyen saate kaydırır.
            mesaj = ('%s saati %s geçti, çalışmadı' % (son.strftime('%H:%M'), str(simdi - son).split('.')[0])
                     if son else 'kayıtlı saat yok, çalışmadı')
            log('zamanlanmış tetik: ' + mesaj)
            json_yaz(DURUM, {'durum': 'gec', 'elle': False, 'basladi': simdi.astimezone().isoformat(),
                             'mesaj': mesaj})
            return
    durum = {'durum': 'suruyor', 'elle': elle, 'basladi': simdi.astimezone().isoformat(), 'simdiki': None,
             'sira_no': 0, 'toplam': 0, 'baslayan': [], 'hatali': [], 'atlanan': []}
    json_yaz(DURUM, durum)
    log('basliyor (%s)' % ('elle' if elle else 'zamanlanmış'))
    try:
        secilen, atlanan = sec(cswap_liste())
        durum.update(toplam=len(secilen), atlanan=atlanan)
        for i, (hesap, eposta) in enumerate(secilen, 1):
            durum.update(simdiki=hesap, sira_no=i)
            json_yaz(DURUM, durum)
            tamam, hata = baslat_bir(eposta)
            if tamam:
                durum['baslayan'].append(hesap)
                log('  %s: pencere başladı' % hesap)
            else:
                durum['hatali'].append({'ad': hesap, 'mesaj': hata})
                log('  %s: başlatılamadı: %s' % (hesap, hata))
        durum['durum'] = 'bitti'
        log('bitti: %d başladı, %d hata, %d atlandı (%s)' % (
            len(durum['baslayan']), len(durum['hatali']), len(atlanan),
            ', '.join('%s: %s' % (a['ad'], a['neden']) for a in atlanan)))
    except Exception as e:
        log('hata: ' + traceback.format_exc())
        durum.update(durum='hata', mesaj=str(e))
    finally:
        durum.update(simdiki=None, bitti=datetime.now().astimezone().isoformat())
        json_yaz(DURUM, durum)


GOREV_PS = r'''
$ErrorActionPreference = 'Stop'
$saatler = @($env:PB_SAATLER -split ',' | Where-Object { $_ })
if ($saatler.Count -eq 0) {
    Unregister-ScheduledTask -TaskName $env:PB_GOREV -Confirm:$false -ErrorAction SilentlyContinue
    exit 0
}
$eylem = New-ScheduledTaskAction -Execute $env:PB_PYTHONW -Argument ('"' + $env:PB_BETIK + '"') -WorkingDirectory $env:PB_KLASOR
$tetikler = @(foreach ($s in $saatler) {
    New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact($s, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture))
})
# Uykudan uyanınca kaçırılan tetik çalışır (StartWhenAvailable); betik 30 dk'dan geç kalındıysa kendisi vazgeçer.
$ayar = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 60) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $env:PB_GOREV -Description 'Claude hesaplarinin 5 saatlik pencerelerini secilen saatte baslatir (claude-account-switcher)' -Action $eylem -Trigger $tetikler -Settings $ayar -Force | Out-Null
'''


def gorev_kur(saatler):
    """Görev Zamanlayıcı'da her saat için günlük tetik; saat yoksa görevi kaldırır. Hata metni ya da ''."""
    pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    # Yollar boşluk ve Türkçe harf içerebilir: komuta gömülmez, ortam değişkeniyle geçer;
    # komut da -EncodedCommand ile (PowerShell 5.1 tırnakları yerel komuta geçirirken bozuyor).
    ortam = dict(os.environ, PB_SAATLER=','.join(saatler), PB_GOREV=GOREV, PB_PYTHONW=pythonw,
                 PB_BETIK=BETIK, PB_KLASOR=KLASOR)
    kod = base64.b64encode(GOREV_PS.encode('utf-16-le')).decode('ascii')
    r = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                        '-EncodedCommand', kod], capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=ortam, creationflags=CREATE_NO_WINDOW, timeout=60)
    if r.returncode != 0:
        return ilk_satir(r.stderr, r.stdout) or 'PowerShell çıkış kodu %s' % r.returncode
    return ''


def main():
    arg = sys.argv[1:]
    if arg[:1] == ['--saatler']:
        saatler = sorted(set(arg[1:]))
        yanlis = [s for s in saatler if not SAAT.match(s)]
        if yanlis:
            yaz('Saat SS:DD olmalı: ' + ', '.join(yanlis))
            return 2
        hata = gorev_kur(saatler)
        if hata:
            yaz('Görev kurulamadı: ' + hata)
            return 1
        json_yaz(AYAR, {'saatler': saatler})
        log('saatler: ' + (', '.join(saatler) or 'yok (görev kaldırıldı)'))
        yaz('Tamam: ' + (', '.join(saatler) or 'görev kaldırıldı'))
        return 0
    if arg[:1] == ['--kur']:
        saatler = saatleri_oku()
        hata = gorev_kur(saatler)
        yaz('5 saatlik başlatma: ' + (hata or ', '.join(saatler) or 'kayıtlı saat yok'))
        return 1 if hata else 0

    # Aynı anda tek kopya: elle basılırken zamanlanmış tetik gelirse ikincisi çıkar.
    kilit = k32.CreateMutexW(None, False, MUTEX)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        log('zaten çalışıyor, bu tetik atlandı')
        return 0
    try:
        calistir(elle='--simdi' in arg)
    finally:
        k32.CloseHandle(ctypes.c_void_p(kilit))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        log('pencere-baslat.pyw hatasi:\n' + traceback.format_exc())
        raise
