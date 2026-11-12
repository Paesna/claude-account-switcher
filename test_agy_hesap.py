"""agy_hesap testleri: gerçek agy girişine ('gemini:antigravity') DOKUNMAZ.

Sahte hedef adları ve geçici veri klasörüyle çalışır; kota komutu sahte bir .bat'tır. Başında ve sonunda gerçek
girişin bozulmadığını doğrular (yalnız okur). Çalıştırma: py -3 test_agy_hesap.py
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest

KLASOR = os.path.dirname(os.path.abspath(__file__))
SUFFIX = str(os.getpid())
GECICI = tempfile.mkdtemp(prefix='agy-hesap-test-')
os.environ['AGY_HESAP_CANLI'] = 'claude-account-switcher:test:canli-' + SUFFIX
os.environ['AGY_HESAP_YEDEK_ONEKI'] = 'claude-account-switcher:test:yedek-%s:' % SUFFIX
os.environ['AGY_HESAP_VERI'] = GECICI
KOTA_METNI = os.path.join(GECICI, 'usage.txt')
KOTA_BAT = os.path.join(GECICI, 'agy-sahte.bat')
with open(KOTA_METNI, 'w', encoding='utf-8', newline='') as f:
    f.write('Gemini Models\tWeekly Limit Remaining\t75%\t2099-11-18T07:29:38Z\r\n'
            'Gemini Models\tFive Hour Limit Remaining\t100%\t2099-11-12T17:58:16Z\r\n'
            'Claude and GPT models\tWeekly Limit Remaining\t100%\t2099-11-19T12:58:16Z\r\n'
            'Claude and GPT models\tFive Hour Limit Remaining\t40%\t2099-11-12T17:58:16Z\r\n')
with open(KOTA_BAT, 'w', encoding='utf-8') as f:
    f.write('@echo off\r\ntype "%~dp0usage.txt"\r\n')
os.environ['AGY_HESAP_KOTA'] = KOTA_BAT
sys.path.insert(0, KLASOR)
import agy_hesap as a  # noqa: E402

GERCEK = 'gemini:antigravity'


def blob(eposta, erisim='erisim-1', yenileme='yenileme-1'):
    return json.dumps({'token': {'access_token': erisim, 'token_type': 'Bearer', 'refresh_token': yenileme,
                                 'expiry': '2099-01-01T00:00:00Z', 'expires_in': 3599},
                       'auth_method': 'oauth', 'id_token_email': eposta, 'writer_id': 'test'}).encode('utf-8')


def gercek_ozet():
    g = a._oku(GERCEK)
    return hashlib.sha256(g[0]).hexdigest() if g else None


class AgyHesap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gercek_once = gercek_ozet()
        a._sil(a.CANLI)

    @classmethod
    def tearDownClass(cls):
        a._sil(a.CANLI)
        for e in ('a@example.com', 'b@example.com'):
            a._sil(a._yedek_hedefi(e))
        assert gercek_ozet() == cls.gercek_once, 'gerçek agy girişi değişti!'

    def test_01_eposta_tanima(self):
        self.assertEqual(a.eposta_of(blob('A@Example.com')), 'a@example.com')
        self.assertIsNone(a.eposta_of(b'{"id_token_email":"a@example.com"}'))          # yenileme anahtarı yok
        self.assertIsNone(a.eposta_of(b'degil json'))
        self.assertIsNone(a.eposta_of(blob('eposta degil')))

    def test_02_kota_cozumu(self):
        with open(KOTA_METNI, encoding='utf-8') as f:
            g = a.kota_coz(f.read())
        self.assertEqual([x['ad'] for x in g], ['Gemini modelleri', 'Claude ve GPT modelleri'])
        self.assertEqual(g[0]['haftalik']['kalan'], 75)
        self.assertEqual(g[1]['bes_saat']['kalan'], 40)
        with self.assertRaises(RuntimeError) as c:
            a.kota_coz('Please sign in to view available models.')
        self.assertIn('sign in', str(c.exception))

    def test_03_dongu(self):
        # giriş yok
        d = a.durum()
        self.assertFalse(d['canli_var'])
        with self.assertRaises(ValueError):
            a.kaydet('x', kota=False)
        # A ile giriş yapılmış, kayıtsız
        a._yaz(a.CANLI, blob('a@example.com'), 'antigravity')
        d = a.durum()
        self.assertEqual((d['canli_eposta'], d['canli_kayitli'], d['hesaplar']), ('a@example.com', False, []))
        # A'yı kaydet (kota fake .bat'tan gelir)
        self.assertIn('kaydedildi', a.kaydet('Hesap A'))
        d = a.durum()
        self.assertTrue(d['canli_kayitli'])
        self.assertEqual([(h['ad'], h['aktif']) for h in d['hesaplar']], [('Hesap A', True)])
        self.assertEqual(d['hesaplar'][0]['kota'][1]['bes_saat']['kalan'], 40)
        # diğer hesapla giriş yapılmış (agy canlı kaydı B'ye çevirdi), B kayıtsız: A'ya geçmek serbest, B'ye dönüş yok
        a._yaz(a.CANLI, blob('b@example.com', 'erisim-b', 'yenileme-b'), 'antigravity')
        d = a.durum()
        self.assertEqual((d['canli_eposta'], d['canli_kayitli']), ('b@example.com', False))
        with self.assertRaises(ValueError) as c:
            a.gec('a@example.com')                      # B kayıtsız: kaybolur, reddedilmeli
        self.assertIn('kayıtlı değil', str(c.exception))
        self.assertEqual(a.durum()['canli_eposta'], 'b@example.com')   # reddedilince canlı kayıt bozulmadı
        a.kaydet('Hesap B', kota=False)
        self.assertEqual([h['eposta'] for h in a.durum()['hesaplar']], ['b@example.com', 'a@example.com'])
        # agy B'nin token'ını yeniledi; A'ya geçince yeni token B'nin yedeğine geri alınmalı
        a._yaz(a.CANLI, blob('b@example.com', 'erisim-b-YENI', 'yenileme-b'), 'antigravity')
        self.assertIn('Hesap A', a.gec('a@example.com'))
        self.assertEqual(a.durum()['canli_eposta'], 'a@example.com')
        yedek_b = json.loads(a._oku(a._yedek_hedefi('b@example.com'))[0])
        self.assertEqual(yedek_b['token']['access_token'], 'erisim-b-YENI')
        # zaten aktif
        with self.assertRaises(ValueError):
            a.gec('a@example.com')
        # kayıtsız hesaba geçiş
        with self.assertRaises(ValueError):
            a.gec('yok@example.com')
        # B'ye dön, A'nın token'ı yenilendi mi? (A canlıydı; geçişte geri alınır)
        a._yaz(a.CANLI, blob('a@example.com', 'erisim-a-YENI', 'yenileme-1'), 'antigravity')
        a.gec('b@example.com')
        self.assertEqual(json.loads(a._oku(a._yedek_hedefi('a@example.com'))[0])['token']['access_token'], 'erisim-a-YENI')
        self.assertEqual(a.durum()['canli_eposta'], 'b@example.com')
        # sil
        self.assertIn('silindi', a.sil('a@example.com'))
        self.assertEqual([h['eposta'] for h in a.durum()['hesaplar']], ['b@example.com'])
        with self.assertRaises(ValueError):
            a.sil('a@example.com')
        # yedeği elle silinen hesap listede görünmez
        a._sil(a._yedek_hedefi('b@example.com'))
        self.assertEqual(a.durum()['hesaplar'], [])

    def test_04_yeni_hesap_once_yedekler_sonra_cikar(self):
        acildi = []
        asil = a.agy_ac
        a.agy_ac = lambda: acildi.append(1)             # gerçek agy penceresi açılmasın
        try:
            a._yaz(a.CANLI, blob('a@example.com'), 'antigravity')
            msg = a.yeni_hesap()
            self.assertIn('yedeklendi', msg)
            self.assertEqual(acildi, [1])
            d = a.durum()
            self.assertFalse(d['canli_var'])
            self.assertEqual([h['eposta'] for h in d['hesaplar']], ['a@example.com'])
            # vazgeç: kayıtlı hesaba geç, canlı kayıt geri gelir
            a.gec('a@example.com')
            self.assertEqual(a.durum()['canli_eposta'], 'a@example.com')
            # tanınmayan canlı kayıt: yedeklenemez, silinmemeli
            a._yaz(a.CANLI, b'tanimsiz', 'antigravity')
            with self.assertRaises(ValueError):
                a.yeni_hesap()
            self.assertIsNotNone(a._oku(a.CANLI))
        finally:
            a.agy_ac = asil


if __name__ == '__main__':
    unittest.main(verbosity=2)
