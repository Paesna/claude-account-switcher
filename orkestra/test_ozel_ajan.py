"""Özel ajan / ajan çıkarma testleri (kota yemez, gerçek CLI çağırmaz).

    py -3 test_ozel_ajan.py            (orkestra klasöründe)
"""
import asyncio
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

KLASOR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KLASOR)
# Hermetik varsayılan: gerçek ajanlar.json'a dokunulmasın; testler kendi geçici dosyasını verir.
os.environ["ORKESTRA_AJANLAR"] = os.path.join(tempfile.gettempdir(), "orkestra-test-yok-%d" % os.getpid(), "ajanlar.json")

# Hermetik: model önbelleği geçici ve TAZE (keşif çalışmaz, gerçek .models_cache.json'a dokunulmaz).
import atexit  # noqa: E402
import model_discovery  # noqa: E402

_MODEL_ONBELLEGI = os.path.join(tempfile.gettempdir(), "orkestra-test-modeller-%d.json" % os.getpid())
with open(_MODEL_ONBELLEGI, "w", encoding="utf-8") as _f:
    json.dump({k: dict(v, taranma=model_discovery.simdi_iso(), kaynak="canli")
               for k, v in model_discovery.FALLBACK_DATA.items()}, _f)
os.environ["MODELS_CACHE"] = _MODEL_ONBELLEGI
atexit.register(lambda: os.path.exists(_MODEL_ONBELLEGI) and os.remove(_MODEL_ONBELLEGI))

import ozel_ajan  # noqa: E402
from adapters import create_adapters  # noqa: E402
from adapters.ozel_adapter import OzelAdapter  # noqa: E402

RUNNER = os.path.join(KLASOR, "runner.py")
PY = sys.executable
ZOR_ISTEM = 'Satır 1\nSatır 2 "tırnaklı" & echo ENJEKSIYON | calc.exe %PATH% ^ <x> {"json": 1} {model}'


def ajan(**ek):
    """Geçerli bir özel ajan: komut olarak bu Python yorumlayıcısı (kurulu, her makinede var)."""
    taban = {"anahtar": "deneme", "ad": "Deneme Ajanı", "komut": PY,
             "argumanlar": ["-c", "print(1)", "{istem_dosyasi}"], "model_arg": ["--m", "{model}"],
             "effort_arg": ["--e", "{effort}"], "istem": "dosya",
             "modeller": ["a/b-1", "c:d[2]"], "efforlar": ["high", "max"],
             "varsayilan_model": "a/b-1", "varsayilan_effort": "high"}
    taban.update(ek)
    return taban


class GeciciAyar(unittest.TestCase):
    """Her test kendi ajanlar.json'u ve ORKESTRA_AJANLAR ortamıyla çalışır."""

    def setUp(self):
        self.kok = tempfile.TemporaryDirectory()
        self.addCleanup(self.kok.cleanup)
        self.yol = os.path.join(self.kok.name, "alt", "ajanlar.json")
        self.eski = os.environ.get("ORKESTRA_AJANLAR")
        os.environ["ORKESTRA_AJANLAR"] = self.yol
        self.addCleanup(self._geri)

    def _geri(self):
        os.environ["ORKESTRA_AJANLAR"] = self.eski

    def runner(self, *arg):
        r = subprocess.run([PY, RUNNER, *arg], capture_output=True, text=True, encoding="utf-8",
                           env=dict(os.environ, PYTHONUTF8="1"), timeout=60)
        satirlar = [json.loads(s) for s in r.stdout.splitlines() if s.strip()]
        return r.returncode, satirlar, r.stderr

    def spec_yaz(self, **ek):
        yol = os.path.join(self.kok.name, "spec.json")
        with open(yol, "w", encoding="utf-8") as f:
            json.dump(ajan(**ek), f)
        return yol


class Dogrulama(unittest.TestCase):
    def hata(self, parca, **ek):
        with self.assertRaises(ValueError) as c:
            ozel_ajan.dogrula_ajan(ajan(**ek))
        self.assertIn(parca.lower(), str(c.exception).lower())

    def test_gecerli_ajan_normallesir(self):
        a = ozel_ajan.dogrula_ajan(ajan(ikon="", bilinmeyen_alan=1))
        self.assertEqual(a["ikon"], "[De]")
        self.assertNotIn("bilinmeyen_alan", a)
        self.assertEqual(a["modeller"], ["a/b-1", "c:d[2]"])
        # MiMo ön ayarı geçerli olmalı (komut bu makinede kurulu değilse yalnız bulunamadı hatası verir)
        m = ozel_ajan.dogrula_ajan(ozel_ajan.MIMO_ONAYARI, kurulu_denetle=False)
        self.assertEqual(m["anahtar"], "mimo")

    def test_anahtar_kurallari(self):
        self.hata("anahtar", anahtar="Mimo")
        self.hata("anahtar", anahtar="m")
        self.hata("anahtar", anahtar="1abc")
        self.hata("anahtar", anahtar="a" * 21)
        self.hata("yerleşik", anahtar="claude")
        self.hata("yerleşik", anahtar="muse")
        with self.assertRaises(ValueError) as c:
            ozel_ajan.dogrula_ajan(ajan(), mevcut_anahtarlar=["deneme"])
        self.assertIn("zaten var", str(c.exception))

    def test_komut_bulunamadi(self):
        self.hata("bulunamadı", komut="yok-boyle-bir-komut-xyz.exe")
        self.hata("tırnak", komut='"' + PY + '"')
        ozel_ajan.dogrula_ajan(ajan(komut="yok-boyle-bir-komut-xyz.exe"), kurulu_denetle=False)

    def test_istem_ve_yer_tutucu_kurallari(self):
        self.hata("{istem_dosyasi}", argumanlar=["-c", "print(1)"])                  # dosya ama yer tutucu yok
        self.hata("stdin", istem="stdin")                                             # stdin ama yer tutucu var
        self.hata("{model}", model_arg=["--m", "x"])
        self.hata("{effort}", effort_arg=["--e"])
        self.hata("'dosya' ya da 'stdin'", istem="argüman")
        ok = ozel_ajan.dogrula_ajan(ajan(istem="stdin", argumanlar=["-c", "print(1)"]))
        self.assertEqual(ok["istem"], "stdin")

    def test_enjeksiyon_ve_uzunluk(self):
        self.hata("model", modeller=["a&b"], varsayilan_model="")
        self.hata("model", modeller=["a b"], varsayilan_model="")
        self.hata("model", modeller=["x" * 81], varsayilan_model="")
        self.hata("seviye", efforlar=["High"], varsayilan_effort="")
        self.hata("seviye", efforlar=["a;b"], varsayilan_effort="")
        self.hata("en çok 40", ad="x" * 41)
        self.hata("500", argumanlar=["{istem_dosyasi}", "x" * 501])
        self.hata("40 öğe", argumanlar=["{istem_dosyasi}"] + ["a"] * 40)
        self.hata("satır sonu", argumanlar=["{istem_dosyasi}", "a\nb"])
        self.hata("satır sonu", argumanlar=["{istem_dosyasi}", "a\x00b"])
        self.hata("denetim", ad="a\nb")
        self.hata("en çok 30", modeller=["m%d" % i for i in range(31)], varsayilan_model="")

    def test_tur_ve_varsayilan_hatalari(self):
        self.hata("liste", argumanlar="run")
        self.hata("metin", ad=5)
        self.hata("metin", komut=None)
        self.hata("listesinde yok", varsayilan_model="olmayan")
        self.hata("listesinde yok", varsayilan_effort="ultra")
        with self.assertRaises(ValueError):
            ozel_ajan.dogrula_ajan(["liste"])


class AyarDosyasi(GeciciAyar):
    def test_yoksa_bos_bozuksa_bos(self):
        self.assertEqual(ozel_ajan.yukle(), {"gizli": [], "ozel": []})
        os.makedirs(os.path.dirname(self.yol))
        with open(self.yol, "w", encoding="utf-8") as f:
            f.write("{bozuk json")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(ozel_ajan.yukle(), {"gizli": [], "ozel": []})
        self.assertIn("okunamadı", err.getvalue())

    def test_gecersiz_kayitlar_uyariyla_atlanir(self):
        os.makedirs(os.path.dirname(self.yol))
        with open(self.yol, "w", encoding="utf-8") as f:
            json.dump({"gizli": ["muse", "bilinmeyen", "muse"],
                       "ozel": [ajan(), ajan(anahtar="claude"), ajan(anahtar="deneme"), "x",
                                ajan(anahtar="kayip", komut="yok-boyle-bir-komut-xyz.exe")]}, f)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            a = ozel_ajan.yukle()
        self.assertEqual(a["gizli"], ["muse"])                                   # bilinmeyen/yinelenen elendi
        # geçerli olan ve komutu sonradan kaybolan ajan (kurulu denetimi yüklemede yok) kalır
        self.assertEqual([o["anahtar"] for o in a["ozel"]], ["deneme", "kayip"])
        self.assertEqual(err.getvalue().count("atlandı"), 3)                      # claude, yinelenen, "x"

    def test_atomik_yazim_artik_birakmaz(self):
        ozel_ajan.kaydet({"gizli": ["agy"], "ozel": []})
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.yol))), ["ajanlar.json"])
        with open(self.yol, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"gizli": ["agy"], "ozel": []})

    def test_ekle_sil_gizle_geri_dongusu(self):
        a = ozel_ajan.ekle(ajan())
        self.assertEqual(a["anahtar"], "deneme")
        with self.assertRaises(ValueError):
            ozel_ajan.ekle(ajan())                                                # aynı anahtar
        self.assertEqual(ozel_ajan.sil("muse"), "gizlendi")
        with self.assertRaises(ValueError) as c:
            ozel_ajan.sil("muse")
        self.assertIn("zaten", str(c.exception))
        self.assertEqual(ozel_ajan.yukle()["gizli"], ["muse"])
        with self.assertRaises(ValueError):
            ozel_ajan.sil("yok-boyle-ajan")
        with self.assertRaises(ValueError):
            ozel_ajan.geri_al("deneme")                                           # özel ajan geri alınmaz
        with self.assertRaises(ValueError):
            ozel_ajan.geri_al("claude")                                           # gizli değil
        self.assertEqual(ozel_ajan.geri_al("muse"), "geri_alindi")
        self.assertEqual(ozel_ajan.sil("deneme"), "silindi")
        self.assertEqual(ozel_ajan.yukle(), {"gizli": [], "ozel": []})

    def test_son_ajan_cikarilamaz(self):
        for k in ("claude", "agy", "codex"):
            ozel_ajan.sil(k)
        with self.assertRaises(ValueError) as c:
            ozel_ajan.sil("muse")
        self.assertIn("en az bir", str(c.exception).lower())
        ozel_ajan.ekle(ajan())
        ozel_ajan.sil("muse")                                                     # artık özel ajan var: tamam
        with self.assertRaises(ValueError):
            ozel_ajan.sil("deneme")                                               # şimdi son o


class ConfigVeAdaptorler(GeciciAyar):
    def test_gizli_cikar_ozel_eklenir(self):
        import config
        ozel_ajan.sil("muse")
        ozel_ajan.ekle(ajan())
        ozel_ajan.ekle(ajan(anahtar="bos", ad="Boş Ajan", modeller=[], efforlar=[], varsayilan_model="",
                            varsayilan_effort="", model_arg=[], effort_arg=[]))
        saglayicilar = config.get_live_providers()
        self.assertEqual(list(saglayicilar), ["claude", "agy", "codex", "deneme", "bos"])
        self.assertIn("muse", config.get_live_providers(include_hidden=True))
        d = saglayicilar["deneme"]
        self.assertEqual((d.name, d.binary, d.default_model, d.default_effort), ("Deneme Ajanı", PY, "a/b-1", "high"))
        self.assertEqual([m.id for m in d.models], ["a/b-1", "c:d[2]"])
        b = saglayicilar["bos"]                                                   # liste boşsa tek "default"
        self.assertEqual(([m.id for m in b.models], b.efforts, b.default_model, b.default_effort),
                         (["default"], ["default"], "default", "default"))

    def test_adaptorlerde_ozel_ajan_var(self):
        ozel_ajan.ekle(ajan())
        ad = create_adapters(models_override={"deneme": "c:d[2]"}, efforts_override={"deneme": "max"})
        self.assertIsInstance(ad["deneme"], OzelAdapter)
        self.assertEqual((ad["deneme"].default_model, ad["deneme"].default_effort), ("c:d[2]", "max"))
        self.assertEqual(set(ad), {"claude", "agy", "codex", "muse", "deneme"})


class OzelAdapterHazirlik(unittest.TestCase):
    def test_dosya_kipi(self):
        a = OzelAdapter(ozel_ajan.dogrula_ajan(ajan(argumanlar=["run", "--dir", "{klasor}", "mesaj", "-f", "{istem_dosyasi}",
                                                                 '{"a": {"b": 1}}'])))
        cmd, stdin, temp = a.prepare(ZOR_ISTEM, model="c:d[2]", effort="max", cwd="C:\\proje")
        try:
            self.assertIsNone(stdin)
            self.assertEqual(len(temp), 1)
            self.assertFalse(any("ENJEKSIYON" in p or "Satır" in p for p in cmd))   # istem komutta yok
            self.assertEqual(cmd[1:5], ["run", "--dir", "C:\\proje", "mesaj"])
            self.assertEqual(cmd[5:7], ["-f", temp[0]])
            self.assertEqual(cmd[7], '{"a": {"b": 1}}')                              # JSON süslü parantezi bozulmadı
            self.assertEqual(cmd[8:], ["--m", "c:d[2]", "--e", "max"])
            with open(temp[0], encoding="utf-8") as f:
                self.assertEqual(f.read(), ZOR_ISTEM)
        finally:
            for t in temp:
                os.remove(t)

    def test_stdin_kipi_ve_varsayilanlar(self):
        a = OzelAdapter(ozel_ajan.dogrula_ajan(ajan(istem="stdin", argumanlar=["exec", "-"])))
        cmd, stdin, temp = a.prepare(ZOR_ISTEM)
        self.assertEqual(stdin, ZOR_ISTEM.encode("utf-8"))
        self.assertEqual(temp, [])
        self.assertEqual(cmd[1:], ["exec", "-", "--m", "a/b-1", "--e", "high"])      # varsayılan model/seviye

    def test_default_ve_bos_model_argumani_eklemez(self):
        a = OzelAdapter(ozel_ajan.dogrula_ajan(ajan(modeller=[], efforlar=[], varsayilan_model="", varsayilan_effort="")))
        self.assertEqual((a.default_model, a.default_effort), ("default", "default"))
        cmd, _, temp = a.prepare("x")
        os.remove(temp[0])
        self.assertNotIn("--m", cmd)
        self.assertNotIn("--e", cmd)

    def test_yer_tutucu_tek_gecisle_dolar(self):
        # Klasör adında '{model}' yazıyorsa model değeriyle yeniden genişletilmemeli.
        a = OzelAdapter(ozel_ajan.dogrula_ajan(ajan(argumanlar=["{klasor}", "{istem_dosyasi}"])))
        cmd, _, temp = a.prepare("x", model="a/b-1", cwd="C:\\x\\{model}\\{effort}")
        os.remove(temp[0])
        self.assertEqual(cmd[1], "C:\\x\\{model}\\{effort}")

    def test_ansi_temizlenir(self):
        a = OzelAdapter(ozel_ajan.dogrula_ajan(ajan()))
        self.assertEqual(a.temizle("\x1b[0m\x1b[91m\x1b[1mError: \x1b[0mmetin\x1b]0;baslik\x07 sonu"), "Error: metin sonu")


class GercekCalistirma(GeciciAyar):
    def _calistir(self, spec, istem):
        a = OzelAdapter(ozel_ajan.dogrula_ajan(spec))
        canli = []
        with tempfile.TemporaryDirectory() as klasor:
            kod, cikti, _ = asyncio.run(a.execute(istem, cwd=klasor, on_output=canli.append, timeout=60))
        return kod, cikti, canli

    def test_dosya_kipinde_istem_dosyadan_okunur_ve_temizlenir(self):
        kod_py = "import sys; sys.stdout.write(open(sys.argv[1], encoding='utf-8').read())"
        spec = ajan(argumanlar=["-X", "utf8", "-c", kod_py, "{istem_dosyasi}"], model_arg=[], effort_arg=[])
        gecici = tempfile.gettempdir()
        once = {f for f in os.listdir(gecici) if f.startswith("deneme-istem-")}
        kod, cikti, _ = self._calistir(spec, ZOR_ISTEM)
        self.assertEqual(kod, 0)
        self.assertEqual(cikti.replace("\r\n", "\n"), ZOR_ISTEM)
        self.assertEqual({f for f in os.listdir(gecici) if f.startswith("deneme-istem-")}, once)  # geçici dosya silindi

    def test_stdin_kipinde_istem_stdinden_okunur_ansi_temizlenir(self):
        kod_py = "import sys; sys.stdout.write(chr(27) + '[91mMERHABA' + chr(27) + '[0m ' + sys.stdin.read())"
        spec = ajan(istem="stdin", argumanlar=["-X", "utf8", "-c", kod_py], model_arg=[], effort_arg=[])
        kod, cikti, canli = self._calistir(spec, ZOR_ISTEM)
        self.assertEqual((kod, cikti.replace("\r\n", "\n")), (0, "MERHABA " + ZOR_ISTEM))
        self.assertFalse(any("\x1b" in p for p in canli))


class RunnerKipleri(GeciciAyar):
    def test_ekle_sil_geri_ve_katalog(self):
        # özel ajan ekle
        kod, o, _ = self.runner("--ajan-ekle", self.spec_yaz())
        self.assertEqual((kod, len(o)), (0, 1))
        self.assertEqual(set(o[0]), {"t", "anahtar", "islem", "mesaj"})
        self.assertEqual((o[0]["t"], o[0]["anahtar"], o[0]["islem"]), ("tamam", "deneme", "eklendi"))
        # yerleşik ajanı çıkar (claude: varsayılan şef değişmeli)
        kod, o, _ = self.runner("--ajan-sil", "claude")
        self.assertEqual((kod, o[0]["islem"]), (0, "gizlendi"))
        kod, o, _ = self.runner("--katalog")
        k = o[0]
        self.assertEqual(kod, 0)
        self.assertEqual([s["anahtar"] for s in k["saglayicilar"]], ["agy", "codex", "muse", "deneme"])
        self.assertEqual(k["gizli"], [{"anahtar": "claude", "ad": "Claude Code"}])
        self.assertEqual(k["varsayilan_sef"], "agy")
        self.assertEqual(k["varsayilan_isciler"], ["agy", "codex", "muse"])           # özel ajan varsayılan işçi değil
        ozel = next(s for s in k["saglayicilar"] if s["anahtar"] == "deneme")
        self.assertIs(ozel["ozel"], True)
        self.assertIs(ozel["kurulu"], True)
        self.assertEqual((ozel["varsayilan_model"], ozel["varsayilan_effort"]), ("a/b-1", "high"))
        self.assertEqual([m["id"] for m in ozel["modeller"]], ["a/b-1", "c:d[2]"])
        # codex'i de çıkar: varsayilan_isciler görünür olanlar
        self.runner("--ajan-sil", "codex")
        k = self.runner("--katalog")[1][0]
        self.assertEqual(k["varsayilan_isciler"], ["agy", "muse"])
        # geri al
        kod, o, _ = self.runner("--ajan-geri", "claude")
        self.assertEqual((kod, o[0]["islem"]), (0, "geri_alindi"))
        k = self.runner("--katalog")[1][0]
        self.assertEqual(k["varsayilan_sef"], "claude")
        self.assertEqual([g["anahtar"] for g in k["gizli"]], ["codex"])
        # özel ajanı sil
        kod, o, _ = self.runner("--ajan-sil", "deneme")
        self.assertEqual((kod, o[0]["islem"]), (0, "silindi"))
        self.assertNotIn("deneme", [s["anahtar"] for s in self.runner("--katalog")[1][0]["saglayicilar"]])

    def test_hatalar_tek_satir_hata_exit1(self):
        for arg, parca in ((("--ajan-sil", "yok-boyle"), "bilinmeyen"), (("--ajan-geri", "claude"), "zaten listede"),
                           (("--ajan-ekle", os.path.join(self.kok.name, "yok.json")), "")):
            kod, o, _ = self.runner(*arg)
            self.assertEqual(kod, 1, arg)
            self.assertEqual((len(o), o[0]["t"]), (1, "hata"), arg)
            self.assertIn(parca, o[0]["mesaj"].lower(), arg)
        kod, o, _ = self.runner("--ajan-ekle", self.spec_yaz(komut="yok-boyle-bir-komut-xyz.exe"))
        self.assertEqual((kod, o[0]["t"]), (1, "hata"))
        self.assertIn("bulunamadı", o[0]["mesaj"])
        self.assertFalse(os.path.exists(self.yol))                                    # hatalı ekleme dosya yazmaz

    def test_gizli_ajan_calistirmada_bilinmeyen(self):
        self.runner("--ajan-sil", "muse")
        with tempfile.TemporaryDirectory() as klasor:
            yol = os.path.join(klasor, "spec.json")
            with open(yol, "w", encoding="utf-8") as f:
                json.dump({"hedef": "x", "sef": "claude", "isciler": ["muse"], "klasor": klasor}, f)
            kod, o, _ = self.runner("--calistir", yol, "--sahte")
        self.assertEqual((kod, o[-1]["t"]), (1, "hata"))
        self.assertIn("bilinmeyen işçi", o[-1]["mesaj"].lower())

    def test_sahte_kipte_ozel_ajan_isci_olur(self):
        self.runner("--ajan-ekle", self.spec_yaz())
        with tempfile.TemporaryDirectory() as klasor:
            yol = os.path.join(klasor, "spec.json")
            with open(yol, "w", encoding="utf-8") as f:
                json.dump({"hedef": "Sahte hedef", "sef": "claude", "isciler": ["deneme", "agy"], "klasor": klasor,
                           "modeller": {"deneme": "c:d[2]"}, "eforlar": {"deneme": "max"}}, f)
            kod, o, err = self.runner("--calistir", yol, "--sahte")
        self.assertEqual(kod, 0, err)
        self.assertEqual(o[0]["isciler"], ["deneme", "agy"])
        planlar = [x["gorevler"] for x in o if x["t"] == "plan"]
        self.assertEqual([g["isci"] for g in planlar[0]], ["deneme", "agy"])
        self.assertEqual([g["durum"] for g in planlar[-1]], ["FINISHED", "FINISHED"])
        self.assertEqual(o[-1]["t"], "bitti")
        # özel ajan şef de olabilir
        with tempfile.TemporaryDirectory() as klasor:
            yol = os.path.join(klasor, "spec.json")
            with open(yol, "w", encoding="utf-8") as f:
                json.dump({"hedef": "x", "sef": "deneme", "isciler": [], "klasor": klasor}, f)
            kod, o, err = self.runner("--calistir", yol, "--sahte")
        self.assertEqual((kod, o[0]["sef"], o[0]["isciler"]), (0, "deneme", ["deneme"]), err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
