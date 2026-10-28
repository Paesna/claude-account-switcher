"""Durum satırı kotayı eşikte görünce hesabı hemen değiştirir (isteğe bağlı hızlı tetik).

cswap auto kullanımı Anthropic'ten en sık dakikada bir okuyabiliyor (hesap başına
saatte ~30 istek sınırı); çok oturum açıkken hesap dakikada birkaç puan eriyor ve
eşiği aşıp %100'e dayanabiliyordu. Claude Code durum satırına her yanıtta güncel
yüzdeyi bedavaya veriyor; durum satırı betiğiniz eşiği görünce bunu çağırırsa geçiş
beklemeden olur. cswap auto yedekte çalışmaya devam eder (haftalık pencere yalnız onda).

  esikte-gec.py            en çok kotası kalan hesaba geç
  esikte-gec.py --deneme   geçmeden cswap'in çalıştığını göster
"""
import os
import subprocess
import sys
import time

CSWAP = os.path.expanduser(r'~\.local\bin\cswap.exe')
GECIS_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gecisler.log')
# Çıktı bir günlüğe yönlenebiliyor; UTF-8 zorlanmazsa cswap'in ├ ve İ harfleri
# yerel kod sayfasına yazılamayıp geçiş yarıda patlardı.
ORTAM = dict(os.environ, PYTHONUTF8='1')
sys.stdout.reconfigure(encoding='utf-8')

komut = [CSWAP, 'status'] if sys.argv[1:] == ['--deneme'] else [CSWAP, 'switch', '--strategy', 'best']
r = subprocess.run(komut, env=ORTAM, capture_output=True, text=True, encoding='utf-8', errors='replace')
ilk = next((s for s in (r.stdout + r.stderr).splitlines() if s.strip()), '')
# Saat başta: Claude hesapları penceresi hızlı geçişleri bu satırdan okuyor.
satir = time.strftime('%Y-%m-%d %H:%M:%S ') + 'cswap %s (kod %d, kota %%%s): %s' % (
    komut[1], r.returncode, os.environ.get('KOTA_YUZDE', '?'), ilk)
print(satir, flush=True)
if komut[1] == 'switch':
    with open(GECIS_LOG, 'a', encoding='utf-8') as f:
        f.write(satir + '\n')
