"""İsteğe bağlı hızlı tetik: Claude Code durum satırı betiği.

Claude Code her yanıttan sonra durum satırı komutunu çalıştırır ve stdin'e o anki
kullanımı verir (rate_limits.five_hour ve rate_limits.seven_day). Bu betik kısa bir
satır yazar ve 5 saatlik veya haftalık kullanım kendi eşiğine gelince esikte-gec.py'yi
arka planda başlatır. Böylece geçiş, cswap auto'nun dakikalık kontrolünü beklemeden olur.

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

KLASOR = os.path.dirname(os.path.abspath(__file__))
ISARETLER = os.path.join(KLASOR, 'tetik')
CSWAP_AYAR = os.path.expanduser(r'~\.claude-swap-backup\settings.json')


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

    saatlik_sinir = esik()
    h_sinir = haftalik_esik()

    saatlik_dolu = yuzde is not None and sifirlanma and yuzde >= saatlik_sinir
    haftalik_dolu = h_yuzde is not None and h_sifirlanma and h_sinir is not None and h_yuzde >= h_sinir

    if not saatlik_dolu and not haftalik_dolu:
        return

    # Aynı pencerede ikinci kez tetiklemesin: geçişten sonra eski oturumlar eski hesabın
    # yüzdesini bir süre daha yazabiliyor. O_EXCL: aynı anda eşiği gören iki oturumdan biri.
    isaret = str(sifirlanma) if saatlik_dolu else ('w_' + str(h_sifirlanma))
    os.makedirs(ISARETLER, exist_ok=True)
    try:
        os.close(os.open(os.path.join(ISARETLER, isaret), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return

    # Durum satırı hemen dönmeli; geçiş ayrı ve penceresiz süreçte yapılır.
    bayrak = 0x00000008 | 0x08000000 | 0x00000200  # DETACHED | CREATE_NO_WINDOW | NEW_PROCESS_GROUP
    kota_metni = str(int(yuzde)) if saatlik_dolu else (str(int(h_yuzde)) + ' hafta')
    subprocess.Popen([sys.executable, os.path.join(KLASOR, 'esikte-gec.py')], creationflags=bayrak,
                     close_fds=True, env=dict(os.environ, KOTA_YUZDE=kota_metni),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
