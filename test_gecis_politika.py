"""gecis_politika.py ve esikte-gec.py'nin Fable sınırı / öncelik davranışı. Kota yemez; gerçek ayar, günlük ve
cswap'a dokunmaz (GECIS_AYAR geçici dosya, cswap çağrıları sahte). Çalıştırma: py -3 test_gecis_politika.py"""
import contextlib
import importlib.util
import io
import json
import math
import os
import random
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

KLASOR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KLASOR)
import gecis_politika as gp  # noqa: E402

SIMDI = time.time()
GELECEK = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
GECMIS = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def hesap(no, p5=0.0, p7=0.0, fable=None, fable_reset=GELECEK, email=None, active=False, disabled=False,
          durum='ok', p5_reset=GELECEK, p7_reset=GELECEK):
    """cswap list --json hesap satırı."""
    usage = {'fiveHour': {'pct': p5, 'resetsAt': p5_reset}, 'sevenDay': {'pct': p7, 'resetsAt': p7_reset}}
    if fable is not None:
        usage['scoped'] = [{'name': 'Fable', 'pct': fable, 'resetsAt': fable_reset}]
    return {'number': no, 'email': email or 'h%d@example.com' % no, 'active': active, 'disabled': disabled,
            'usageStatus': durum, 'usage': usage}


def eski_hedef_sec(hesaplar, aktif, simdi, esik, h_esik, aktif_yuzde):
    """esikte-gec.py'nin Fable/öncelikten ÖNCEKİ hedef_sec'i (karşılaştırma için kopya)."""
    en_iyi = yedek = None
    for s in hesaplar:
        if s is aktif or s.get('active') or s.get('disabled') or s.get('usageStatus') != 'ok':
            continue
        p5 = gp.kayit(s, 'fiveHour', simdi)[0] or 0.0
        p7 = gp.kayit(s, 'sevenDay', simdi)[0] or 0.0
        if p5 < esik and p7 < h_esik:
            doluluk = max(p5 / esik, p7 / h_esik)
            if en_iyi is None or doluluk < en_iyi[0]:
                en_iyi = (doluluk, s)
        elif aktif_yuzde is not None and max(p5, p7) < min(99.0, aktif_yuzde - 5) \
                and (yedek is None or max(p5, p7) < yedek[0]):
            yedek = (max(p5, p7), s)
    secilen = en_iyi or yedek
    return secilen[1] if secilen else None


class AyarOrtami(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp(prefix='gecis-test-')
        self.yol = os.path.join(self.klasor, 'gecis-ayar.json')
        self._eski = os.environ.get('GECIS_AYAR')
        os.environ['GECIS_AYAR'] = self.yol

    def tearDown(self):
        if self._eski is None:
            os.environ.pop('GECIS_AYAR', None)
        else:
            os.environ['GECIS_AYAR'] = self._eski
        for ad in os.listdir(self.klasor):
            os.remove(os.path.join(self.klasor, ad))
        os.rmdir(self.klasor)


class HedefSecimi(unittest.TestCase):
    def test_fable_ve_oncelik_yokken_eskisiyle_birebir_ayni(self):
        rnd = random.Random(7)
        for _ in range(500):
            n = rnd.randint(0, 9)
            liste = []
            for i in range(1, n + 1):
                liste.append(hesap(
                    i, p5=rnd.choice([None, 0, 10, 55, 89, 90, 100, rnd.uniform(0, 100)]),
                    p7=rnd.choice([None, 0, 30, 70, 99, 100, rnd.uniform(0, 100)]),
                    fable=rnd.choice([None, 0, 45, 99]),
                    active=(i == 1 and rnd.random() < .5), disabled=rnd.random() < .15,
                    durum=rnd.choice(['ok', 'ok', 'ok', 'error']),
                    p5_reset=rnd.choice([GELECEK, GELECEK, GECMIS, None])))
            aktif = rnd.choice(liste) if liste else None
            esik, h_esik = rnd.choice([(90.0, 90.0), (89.0, 99.0), (80.0, 95.0)])
            for ay in (None, 100.0, 97.0, 91.0):
                beklenen = eski_hedef_sec(liste, aktif, SIMDI, esik, h_esik, ay)
                self.assertIs(gp.hedef_sec(liste, aktif, SIMDI, esik, h_esik, ay), beklenen)
                self.assertIs(gp.hedef_sec(liste, aktif, SIMDI, esik, h_esik, ay, None, []), beklenen)
                self.assertIs(gp.hedef_sec(liste, aktif, SIMDI, esik, h_esik, ay, fable_esik=None, oncelik=None), beklenen)

    def test_fable_siniri_eler(self):
        a = hesap(1, 10, 10, fable=60)      # en boş ama Fable'ı yüksek
        b = hesap(2, 20, 20, fable=30)
        aktif = hesap(9, 95, 10, active=True)
        liste = [aktif, a, b]
        self.assertIs(gp.hedef_sec(liste, aktif, SIMDI, 90, 90, None), a)
        self.assertIs(gp.hedef_sec(liste, aktif, SIMDI, 90, 90, None, fable_esik=50), b)
        self.assertIs(gp.hedef_sec(liste, aktif, SIMDI, 90, 90, None, fable_esik=70), a)
        self.assertIs(gp.hedef_sec(liste, aktif, SIMDI, 90, 90, None, fable_esik=60), b)  # sınırda: elenir (>=)

    def test_fable_okunamayan_hesap_elenmez(self):
        a = hesap(1, 10, 10)                 # Fable bilgisi hiç yok
        b = hesap(2, 20, 20, fable=90)
        aktif = hesap(9, 95, 10, active=True)
        self.assertIs(gp.hedef_sec([aktif, a, b], aktif, SIMDI, 90, 90, None, fable_esik=50), a)
        c = hesap(3, 10, 10)
        c['usage']['scoped'] = [{'name': 'Fable', 'pct': None, 'resetsAt': GELECEK}]
        self.assertIs(gp.hedef_sec([aktif, c], aktif, SIMDI, 90, 90, None, fable_esik=50), c)

    def test_fable_penceresi_sifirlanmissa_sifir_sayilir(self):
        a = hesap(1, 10, 10, fable=95, fable_reset=GECMIS)
        aktif = hesap(9, 95, 10, active=True)
        self.assertEqual(gp.fable_yuzde(a, SIMDI), 0.0)
        self.assertIs(gp.hedef_sec([aktif, a], aktif, SIMDI, 90, 90, None, fable_esik=50), a)

    def test_hepsi_fable_sinirinda_hedef_yok_ama_sinir_hatasinda_yedek_var(self):
        a = hesap(1, 10, 10, fable=80)
        b = hesap(2, 30, 30, fable=85)
        aktif = hesap(9, 95, 10, active=True)
        self.assertIsNone(gp.hedef_sec([aktif, a, b], aktif, SIMDI, 90, 90, None, fable_esik=50))   # eşik/Fable geçişi
        self.assertIs(gp.hedef_sec([aktif, a, b], aktif, SIMDI, 90, 90, 100.0, fable_esik=50), a)    # sınır hatası: en az dolu

    def test_oncelik_listedeki_ilk_uygun(self):
        aktif = hesap(9, 95, 10, active=True, email='aktif@example.com')
        a = hesap(1, 50, 20, email='a@example.com')
        b = hesap(2, 5, 5, email='b@example.com')     # en boş ama listede değil
        c = hesap(3, 80, 30, email='c@example.com')
        d = hesap(4, 20, 20, email='d@example.com')   # listede değil, b'den dolu
        liste = [aktif, a, b, c, d]
        onc = ['c@example.com', 'a@example.com']
        self.assertIs(gp.hedef_sec(liste, aktif, SIMDI, 90, 90, None, oncelik=onc), c)
        # c uygun değil (eşiğin üstünde): sıradaki a
        c2 = hesap(3, 95, 30, email='c@example.com')
        self.assertIs(gp.hedef_sec([aktif, a, b, c2, d], aktif, SIMDI, 90, 90, None, oncelik=onc), a)
        # c devre dışı: a
        c3 = hesap(3, 10, 10, email='c@example.com', disabled=True)
        self.assertIs(gp.hedef_sec([aktif, a, b, c3, d], aktif, SIMDI, 90, 90, None, oncelik=onc), a)
        # c okunamıyor: a
        c4 = hesap(3, 10, 10, email='c@example.com', durum='error')
        self.assertIs(gp.hedef_sec([aktif, a, b, c4, d], aktif, SIMDI, 90, 90, None, oncelik=onc), a)

    def test_oncelik_listede_olmayanlar_sonda_en_bos_kuraliyla(self):
        aktif = hesap(9, 95, 10, active=True)
        b = hesap(2, 30, 30)
        d = hesap(4, 20, 20)
        a = hesap(1, 95, 20, email='a@example.com')   # listede ama uygun değil
        self.assertIs(gp.hedef_sec([aktif, a, b, d], aktif, SIMDI, 90, 90, None, oncelik=['a@example.com']), d)

    def test_oncelik_aktif_hesabi_atlar_ve_buyuk_kucuk_harf_fark_etmez(self):
        aktif = hesap(9, 95, 10, active=True, email='Aktif@Example.com')
        a = hesap(1, 50, 20, email='A@Example.com')
        onc = ['aktif@example.com', 'a@example.com']
        self.assertIs(gp.hedef_sec([aktif, a], aktif, SIMDI, 90, 90, None, oncelik=onc), a)
        # listede tekrar: ilk sıra geçerli
        b = hesap(2, 5, 5, email='b@example.com')
        self.assertIs(gp.hedef_sec([aktif, a, b], aktif, SIMDI, 90, 90, None,
                                    oncelik=['b@example.com', 'a@example.com', 'b@example.com']), b)

    def test_oncelik_fable_siniriyla_birlikte(self):
        aktif = hesap(9, 95, 10, active=True)
        a = hesap(1, 10, 10, fable=70, email='a@example.com')   # öncelikli ama Fable sınırında
        b = hesap(2, 40, 40, fable=20, email='b@example.com')
        self.assertIs(gp.hedef_sec([aktif, a, b], aktif, SIMDI, 90, 90, None, fable_esik=50,
                                    oncelik=['a@example.com', 'b@example.com']), b)

    def test_yedek_dal_oncelikten_bagimsiz(self):
        aktif = hesap(9, 100, 10, active=True)
        a = hesap(1, 94, 10, email='a@example.com')   # öncelikli, eşiğin üstünde
        b = hesap(2, 91, 10, email='b@example.com')   # eşiğin üstünde ama daha az dolu
        liste = [aktif, a, b]
        self.assertIs(gp.hedef_sec(liste, aktif, SIMDI, 90, 90, 100.0, oncelik=['a@example.com']), b)
        self.assertIsNone(gp.hedef_sec(liste, aktif, SIMDI, 90, 90, None, oncelik=['a@example.com']))

    def test_adaylar_aktif_disabled_ve_okunamayan_atlanir(self):
        aktif = hesap(9, 95, 10, active=True)
        digeri_active = hesap(1, 1, 1, active=True)
        dis = hesap(2, 1, 1, disabled=True)
        hatali = hesap(3, 1, 1, durum='error')
        self.assertIsNone(gp.hedef_sec([aktif, digeri_active, dis, hatali], aktif, SIMDI, 90, 90, None,
                                        fable_esik=50, oncelik=['h1@example.com', 'h2@example.com', 'h3@example.com']))


class FableYuzde(unittest.TestCase):
    def test_okuma(self):
        self.assertEqual(gp.fable_yuzde(hesap(1, fable=48.0), SIMDI), 48.0)
        s = hesap(1)
        s['usage']['scoped'] = [{'name': 'Opus', 'pct': 10, 'resetsAt': GELECEK}, {'name': ' FABLE ', 'pct': 33, 'resetsAt': GELECEK}]
        self.assertEqual(gp.fable_yuzde(s, SIMDI), 33.0)
        self.assertIsNone(gp.fable_yuzde(hesap(1), SIMDI))
        self.assertIsNone(gp.fable_yuzde({'usage': None}, SIMDI))
        s['usage']['scoped'] = [{'name': 'Fable', 'pct': 40, 'resetsAt': None}]
        self.assertEqual(gp.fable_yuzde(s, SIMDI), 40.0)


class AyarDogrulama(AyarOrtami):
    def test_gecerli(self):
        n = gp.ayar_normalize({'fable_esigi': 80, 'oncelik_acik': True, 'oncelik': ['A@X.com ', 'b@x.com', 'a@x.com'], 'yok': 1})
        self.assertEqual(n, {'fable_esigi': 80.0, 'oncelik_acik': True, 'oncelik': ['a@x.com', 'b@x.com']})
        self.assertEqual(gp.ayar_normalize({}), gp.varsayilan())
        self.assertEqual(gp.ayar_normalize({'fable_esigi': 99.9})['fable_esigi'], 99.9)
        self.assertEqual(gp.ayar_normalize({'fable_esigi': 50})['fable_esigi'], 50.0)
        self.assertIsNone(gp.ayar_normalize({'fable_esigi': None})['fable_esigi'])

    def test_hatalar(self):
        for kotu in (True, False, '80', 49, 49.9, 100, 99.91, -1, float('nan'), float('inf'), [80]):
            with self.assertRaises(ValueError, msg=repr(kotu)):
                gp.ayar_normalize({'fable_esigi': kotu})
        for kotu in ('evet', 1, 0, [], {}):
            with self.assertRaises(ValueError, msg=repr(kotu)):
                gp.ayar_normalize({'oncelik_acik': kotu})
        for kotu in ('a@x.com', ['eposta degil'], ['a@x.com', 5], [None], ['a b@x.com'], ['@x.com'], ['a@'], {'a': 1}):
            with self.assertRaises(ValueError, msg=repr(kotu)):
                gp.ayar_normalize({'oncelik': kotu})
        with self.assertRaises(ValueError):
            gp.ayar_normalize({'oncelik': ['h%d@x.com' % i for i in range(201)]})
        self.assertEqual(len(gp.ayar_normalize({'oncelik': ['h%d@x.com' % i for i in range(200)]})['oncelik']), 200)
        for kotu in (None, [], 'x', 5):
            with self.assertRaises(ValueError):
                gp.ayar_normalize(kotu)

    def test_hata_mesaji_turkce_ve_degeri_sizdirmaz(self):
        with self.assertRaises(ValueError) as c:
            gp.ayar_normalize({'fable_esigi': 49})
        self.assertIn('Fable sınırı', str(c.exception))

    def test_ayar_oku_dosya_yok_ya_da_bozuk(self):
        self.assertEqual(gp.ayar_oku(), gp.varsayilan())
        for icerik in ('{bozuk', '', '[]', '"x"', 'null', '\x00\x01'):
            with open(self.yol, 'w', encoding='utf-8') as f:
                f.write(icerik)
            self.assertEqual(gp.ayar_oku(), gp.varsayilan(), icerik)
        with open(self.yol, 'wb') as f:
            f.write(b'\xff\xfe\x00bozuk-kodlama')
        self.assertEqual(gp.ayar_oku(), gp.varsayilan())

    def test_ayar_oku_alan_bazli_ve_bom(self):
        with open(self.yol, 'w', encoding='utf-8-sig') as f:   # BOM'lu (PowerShell yazımı)
            json.dump({'fable_esigi': 10, 'oncelik_acik': True, 'oncelik': ['B@x.com']}, f)
        # fable_esigi geçersiz -> varsayılana düşer, ötekiler korunur
        self.assertEqual(gp.ayar_oku(), {'fable_esigi': None, 'oncelik_acik': True, 'oncelik': ['b@x.com']})

    def test_ayar_yaz_atomik_ve_geri_okunur(self):
        d = gp.ayar_yaz({'fable_esigi': 75, 'oncelik_acik': True, 'oncelik': ['a@x.com', 'B@x.com']})
        self.assertEqual(d, {'fable_esigi': 75.0, 'oncelik_acik': True, 'oncelik': ['a@x.com', 'b@x.com']})
        self.assertEqual(gp.ayar_oku(), d)
        self.assertEqual(os.listdir(self.klasor), ['gecis-ayar.json'])          # geçici dosya kalmadı
        with open(self.yol, 'rb') as f:
            self.assertNotIn(b'\r', f.read())
        # geçersiz yazım: reddedilir ve eski dosya bozulmaz
        with self.assertRaises(ValueError):
            gp.ayar_yaz({'fable_esigi': 10})
        self.assertEqual(gp.ayar_oku(), d)
        self.assertEqual(os.listdir(self.klasor), ['gecis-ayar.json'])
        # üzerine yaz
        d2 = gp.ayar_yaz({'fable_esigi': None, 'oncelik_acik': False, 'oncelik': []})
        self.assertEqual(gp.ayar_oku(), d2)

    def test_ayar_yaz_klasoru_olusturur(self):
        os.environ['GECIS_AYAR'] = os.path.join(self.klasor, 'alt', 'klasor', 'a.json')
        try:
            gp.ayar_yaz({'fable_esigi': 60})
            self.assertEqual(gp.ayar_oku()['fable_esigi'], 60.0)
        finally:
            os.remove(os.environ['GECIS_AYAR'])
            os.rmdir(os.path.join(self.klasor, 'alt', 'klasor'))
            os.rmdir(os.path.join(self.klasor, 'alt'))

    def test_ayar_yolu_ortami_her_cagrida_okur(self):
        self.assertEqual(gp.AYAR_YOLU(), self.yol)
        os.environ['GECIS_AYAR'] = self.yol + '.baska'
        self.assertEqual(gp.AYAR_YOLU(), self.yol + '.baska')
        del os.environ['GECIS_AYAR']
        yol = gp.AYAR_YOLU()
        self.assertTrue(yol.endswith(os.path.join('claude-account-switcher', 'gecis-ayar.json')), yol)


def esikte_gec_yukle():
    spec = importlib.util.spec_from_file_location('esikte_gec_test', os.path.join(KLASOR, 'esikte-gec.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Cikti(io.StringIO):
    def reconfigure(self, **kw):  # main() sys.stdout.reconfigure çağırıyor
        pass


class EsikteGec(AyarOrtami):
    """esikte-gec.py main(): sahte cswap, --deneme (hiçbir şey yazmaz ve geçmez)."""

    def calistir(self, hesaplar, okuma, eski_ayar=None, esikler=(90.0, 90.0)):
        m = esikte_gec_yukle()
        m.cswap = lambda *a, **k: (0, json.dumps({'schemaVersion': 1, 'accounts': hesaplar}), '')
        m.esikler = lambda: esikler
        m.son_gecis_zamani = lambda: 0
        cikti = _Cikti()
        eski_argv = sys.argv
        sys.argv = ['esikte-gec.py', '--deneme', json.dumps(okuma)]
        try:
            with contextlib.redirect_stdout(cikti):
                kod = m.main()
        finally:
            sys.argv = eski_argv
        return kod, cikti.getvalue().strip(), m

    def okuma(self, p5=10, p7=10):
        return {'five_hour': {'used_percentage': p5, 'resets_at': None}, 'seven_day': {'used_percentage': p7, 'resets_at': None},
                'zaman': time.time()}

    def test_fable_siniri_yokken_fable_yuksekse_gecmez(self):
        liste = [hesap(1, 10, 10, fable=85, active=True), hesap(2, 20, 20, fable=10)]
        kod, cikti, _ = self.calistir(liste, self.okuma())
        self.assertEqual(kod, 0)
        self.assertIn('eşiğin altında (5 saat 10, hafta 10, Fable 85)', cikti)

    def test_fable_siniri_asilinca_gecer_ve_fable_dolu_hesaba_gitmez(self):
        gp.ayar_yaz({'fable_esigi': 80})
        liste = [hesap(1, 10, 10, fable=85, active=True), hesap(2, 5, 5, fable=90), hesap(3, 30, 30, fable=10)]
        kod, cikti, _ = self.calistir(liste, self.okuma())
        self.assertIn('geçilecek: Account-3', cikti)

    def test_fable_siniri_altindaysa_gecmez(self):
        gp.ayar_yaz({'fable_esigi': 90})
        liste = [hesap(1, 10, 10, fable=85, active=True), hesap(3, 30, 30, fable=10)]
        _, cikti, _ = self.calistir(liste, self.okuma())
        self.assertIn('eşiğin altında', cikti)

    def test_fable_tetiginde_uygun_hesap_yoksa_gecmez_yedek_dal_kapali(self):
        gp.ayar_yaz({'fable_esigi': 80})
        liste = [hesap(1, 10, 10, fable=85, active=True), hesap(2, 5, 5, fable=90), hesap(3, 30, 30, fable=95)]
        _, cikti, _ = self.calistir(liste, self.okuma())
        self.assertIn('geçilecek boş hesap yok', cikti)

    def test_oncelik_kapaliyken_listeye_bakmaz_acikken_bakar(self):
        liste = [hesap(1, 95, 10, active=True, email='a1@example.com'), hesap(2, 5, 5, email='h2@example.com'),
                 hesap(3, 40, 40, email='h3@example.com')]
        gp.ayar_yaz({'oncelik_acik': False, 'oncelik': ['h3@example.com']})
        _, cikti, _ = self.calistir(liste, self.okuma(p5=95))
        self.assertIn('geçilecek: Account-2', cikti)            # en boş
        gp.ayar_yaz({'oncelik_acik': True, 'oncelik': ['h3@example.com']})
        _, cikti, _ = self.calistir(liste, self.okuma(p5=95))
        self.assertIn('geçilecek: Account-3', cikti)            # öncelikli

    def test_bozuk_ayar_gecisi_kirmaz(self):
        with open(self.yol, 'w', encoding='utf-8') as f:
            f.write('{bozuk')
        liste = [hesap(1, 95, 10, active=True), hesap(2, 5, 5), hesap(3, 40, 40)]
        kod, cikti, _ = self.calistir(liste, self.okuma(p5=95))
        self.assertEqual(kod, 0)
        self.assertIn('geçilecek: Account-2', cikti)

    def test_ayar_okuma_istisna_atarsa_eski_davranis(self):
        from unittest import mock
        m = esikte_gec_yukle()
        with mock.patch.object(gp, 'ayar_oku', side_effect=RuntimeError('disk')):
            self.assertEqual(m.politika(), (None, None))

    def test_politika_degerleri(self):
        m = esikte_gec_yukle()
        gp.ayar_yaz({'fable_esigi': 70, 'oncelik_acik': True, 'oncelik': ['a@x.com']})
        self.assertEqual(m.politika(), (70.0, ['a@x.com']))
        gp.ayar_yaz({'fable_esigi': 70, 'oncelik_acik': False, 'oncelik': ['a@x.com']})
        self.assertEqual(m.politika(), (70.0, None))


if __name__ == '__main__':
    unittest.main(verbosity=2)
