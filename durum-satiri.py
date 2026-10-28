"""İsteğe bağlı hızlı tetik: Claude Code durum satırı betiği.

Claude Code her yanıttan sonra durum satırı komutunu çalıştırır ve stdin'e o anki
kullanımı verir (rate_limits.five_hour.used_percentage). Bu betik kısa bir satır yazar
ve 5 saatlik kullanım eşiğe gelince esikte-gec.py'yi arka planda başlatır. Böylece
geçiş, cswap auto'nun dakikalık kontrolünü beklemeden olur.

Eşik cswap'ın kendi ayarından okunur (pencereden ya da
`cswap config set autoswitch.threshold 90` ile değişir); iki yerde ayrı tutulsa biri
erken biri geç geçerdi. Her 5 saatlik pencerede bir kez tetikler.

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


def main():
    try:
        veri = json.load(sys.stdin)
    except ValueError:
        veri = {}
    pencere = (veri.get('rate_limits') or {}).get('five_hour') or {}
    yuzde, sifirlanma = pencere.get('used_percentage'), pencere.get('resets_at')
    model = (veri.get('model') or {}).get('display_name') or ''
    sys.stdout.reconfigure(encoding='utf-8')
    if yuzde is None:
        print(model)
        return
    print('%s  ·  5 saat %%%d' % (model, yuzde))
    if yuzde < esik() or not sifirlanma:
        return
    # Aynı pencerede ikinci kez tetiklemesin: geçişten sonra eski oturumlar eski hesabın
    # yüzdesini bir süre daha yazabiliyor. O_EXCL: aynı anda eşiği gören iki oturumdan biri.
    os.makedirs(ISARETLER, exist_ok=True)
    try:
        os.close(os.open(os.path.join(ISARETLER, str(sifirlanma)), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return
    # Durum satırı hemen dönmeli; geçiş ayrı ve penceresiz süreçte yapılır.
    bayrak = 0x00000008 | 0x08000000 | 0x00000200  # DETACHED | CREATE_NO_WINDOW | NEW_PROCESS_GROUP
    subprocess.Popen([sys.executable, os.path.join(KLASOR, 'esikte-gec.py')], creationflags=bayrak,
                     close_fds=True, env=dict(os.environ, KOTA_YUZDE=str(int(yuzde))),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
