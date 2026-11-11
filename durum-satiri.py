"""İsteğe bağlı hızlı tetik: Claude Code durum satırı betiği.

Claude Code her yanıttan sonra durum satırı komutunu çalıştırır ve stdin'e o anki
kullanımı verir (rate_limits.five_hour ve rate_limits.seven_day). Bu betik kısa bir
satır yazar ve yüzde değiştikçe esikte-gec.py --aktar'ı arka planda başlatır: okuma
claude-swap'ın deposuna yazılır (pencere anlık yüzdeyi gösterir), aktif hesap eşikteyse
hemen geçilir. Böylece geçiş, cswap auto'nun dakikalık kontrolünü beklemeden olur.

Eşikler cswap'ın kendi ayarından okunur (pencereden ya da
`cswap config set autoswitch.threshold 90` / `cswap config set autoswitch.weeklyThreshold 95`
ile değişir); iki yerde ayrı tutulsa biri erken biri geç geçerdi.

~/.claude/settings.json:
  "statusLine": {"type": "command", "command": "py -3 \"C:/.../claude account switcher/durum-satiri.py\""}
"""
import json
import os
import subprocess
import sys
import time

KLASOR = os.path.dirname(os.path.abspath(__file__))
AKTARIM = os.path.join(KLASOR, 'tetik', 'aktarim.json')
CSWAP_AYAR = os.path.expanduser(r'~\.claude-swap-backup\settings.json')
AKTAR_ARALIK_SN = 8
ACIL_PAY = 5


def esik():
    try:
        with open(CSWAP_AYAR, encoding='utf-8') as f:
            return float(json.load(f)['autoswitch']['threshold'])
    except Exception:
        return 90.0


def haftalik_esik():
    try:
        with open(CSWAP_AYAR, encoding='utf-8') as f:
            val = json.load(f).get('autoswitch', {}).get('weeklyThreshold')
            return float(val) if val is not None else None
    except Exception:
        return None


def main():
    try:
        veri = json.load(sys.stdin)
    except ValueError:
        veri = {}
    rate_limits = veri.get('rate_limits') or {}
    pencere = rate_limits.get('five_hour') or {}
    pencere_haftalik = rate_limits.get('seven_day') or rate_limits.get('seven_days') or {}

    yuzde, sifirlanma = pencere.get('used_percentage'), pencere.get('resets_at')
    h_yuzde, h_sifirlanma = pencere_haftalik.get('used_percentage'), pencere_haftalik.get('resets_at')
    model = (veri.get('model') or {}).get('display_name') or ''
    sys.stdout.reconfigure(encoding='utf-8')

    parcalar = [model] if model else []
    if yuzde is not None:
        parcalar.append('5 saat %%%d' % yuzde)
    if h_yuzde is not None:
        parcalar.append('hafta %%%d' % h_yuzde)

    if parcalar:
        print('  ·  '.join(parcalar))
    elif model:
        print(model)

    if yuzde is None and h_yuzde is None:
        return
    # Yüzde her değiştiğinde esikte-gec.py --aktar: okumayı claude-swap'ın deposuna yazar
    # (pencere ve cswap auto dakikalık okumayı beklemez), aktif hesap eşikteyse geçer. Hangi
    # hesaba ait olduğunu ve eski bir oturumdan gelip gelmediğini o ayırt eder. Eşiğin
    # altında en sık AKTAR_ARALIK_SN'de bir, eşiğe ACIL_PAY puan kala her değişimde.
    imza = [yuzde, sifirlanma, h_yuzde, h_sifirlanma]
    try:
        with open(AKTARIM, encoding='utf-8') as f:
            onceki = json.load(f)
    except (OSError, ValueError):
        onceki = {}
    if onceki.get('imza') == imza:
        return
    h_sinir = haftalik_esik() or 100.0
    acil = (yuzde or 0) >= esik() - ACIL_PAY or (h_yuzde or 0) >= h_sinir - ACIL_PAY
    simdi = time.time()
    if not acil and simdi - onceki.get('zaman', 0) < AKTAR_ARALIK_SN:
        return
    try:
        os.makedirs(os.path.dirname(AKTARIM), exist_ok=True)
        with open(AKTARIM, 'w', encoding='utf-8') as f:
            json.dump({'imza': imza, 'zaman': simdi}, f)
    except OSError:
        pass
    okuma = {'zaman': simdi}
    if yuzde is not None:
        okuma['five_hour'] = {'used_percentage': yuzde, 'resets_at': sifirlanma}
    if h_yuzde is not None:
        okuma['seven_day'] = {'used_percentage': h_yuzde, 'resets_at': h_sifirlanma}

    # Durum satırı hemen dönmeli; aktarım ve geçiş ayrı ve penceresiz süreçte yapılır.
    bayrak = 0x00000008 | 0x08000000 | 0x00000200  # DETACHED | CREATE_NO_WINDOW | NEW_PROCESS_GROUP
    subprocess.Popen([sys.executable, os.path.join(KLASOR, 'esikte-gec.py'), '--aktar', json.dumps(okuma)],
                     creationflags=bayrak, close_fds=True, env=dict(os.environ),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
