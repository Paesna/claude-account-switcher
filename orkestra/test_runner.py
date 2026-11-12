"""Kota yakmayan birim ve uçtan uca testler (gerçek CLI çağırmaz).

    py -3 test_runner.py            (orkestra klasöründe)
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

KLASOR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KLASOR)
# Hermetik: kullanıcının gerçek ajanlar.json'u (panelden eklenen/gizlenen ajanlar) testleri etkilemesin.
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

from adapters import create_adapters  # noqa: E402
from orchestrator import ConductorOrchestrator  # noqa: E402
from protocol import AgentStatus  # noqa: E402

RUNNER = os.path.join(KLASOR, "runner.py")
ENV = dict(os.environ, PYTHONUTF8="1")
ZOR_ISTEM = 'Satır 1\nSatır 2 "tırnaklı" & echo ENJEKSIYON | calc.exe %PATH% ^ <x> ünicode: şğıöç'


class AdaptorHazirlik(unittest.TestCase):
    def setUp(self):
        self.ad = create_adapters()

    def test_claude_istem_stdin_komutta_yok(self):
        cmd, stdin, temp = self.ad["claude"].prepare(ZOR_ISTEM, model="haiku", effort="high")
        self.assertNotIn(ZOR_ISTEM, " ".join(cmd))
        self.assertFalse(any("ENJEKSIYON" in a or "Satır" in a for a in cmd))
        self.assertEqual(stdin, ZOR_ISTEM.encode("utf-8"))
        self.assertEqual(temp, [])
        self.assertIn("-p", cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "haiku")
        self.assertEqual(cmd[cmd.index("--effort") + 1], "high")

    def test_claude_effort_yalniz_kabul_edilenler(self):
        for efor in ("ultra", "auto", "none"):
            cmd, _, _ = self.ad["claude"].prepare("x", effort=efor)
            self.assertNotIn("--effort", cmd, efor)
        for efor in ("low", "medium", "high", "xhigh", "max"):
            cmd, _, _ = self.ad["claude"].prepare("x", effort=efor)
            self.assertEqual(cmd[cmd.index("--effort") + 1], efor)

    def test_codex_istem_stdin_son_arguman_tire(self):
        cmd, stdin, temp = self.ad["codex"].prepare(ZOR_ISTEM, model="gpt-6-astra", effort="xhigh")
        self.assertFalse(any("ENJEKSIYON" in a or "Satır" in a for a in cmd))
        self.assertEqual(cmd[-1], "-")
        self.assertEqual(stdin, ZOR_ISTEM.encode("utf-8"))
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", cmd)
        self.assertEqual(cmd[cmd.index("-m") + 1], "gpt-6-astra")
        self.assertIn('model_reasoning_effort="xhigh"', cmd)

    def test_muse_istem_gecici_dosyada(self):
        with tempfile.TemporaryDirectory() as klasor:
            cmd, stdin, temp = self.ad["muse"].prepare(ZOR_ISTEM, model="muse-spark", effort="high", cwd=klasor)
            try:
                self.assertIsNone(stdin)
                self.assertEqual(len(temp), 1)
                self.assertFalse(any("ENJEKSIYON" in a or "Satır" in a for a in cmd))
                self.assertEqual(cmd[cmd.index("--prompt-file") + 1], temp[0])
                with open(temp[0], encoding="utf-8") as f:
                    self.assertEqual(f.read(), ZOR_ISTEM)
                self.assertEqual(cmd[cmd.index("--workspace") + 1], klasor)
                self.assertEqual(cmd[cmd.index("--approval-mode") + 1], "never")
                self.assertIn("--user-input-auto-resolve", cmd)
                self.assertNotIn("--yolo", cmd)
                self.assertNotIn("--json", cmd)
                self.assertEqual(cmd[cmd.index("--model") + 1], "muse-spark")
                self.assertEqual(cmd[cmd.index("--reasoning-effort") + 1], "high")
            finally:
                for t in temp:
                    os.remove(t)

    def test_agy_degismedi_istem_argumanda(self):
        cmd, stdin, temp = self.ad["agy"].prepare("kisa istem", model="gemini-3.8-flash-high", effort="high")
        self.assertIsNone(stdin)
        self.assertEqual(temp, [])
        self.assertEqual(cmd[1:5], ["-p", "kisa istem", "--output-format", "text"])
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertEqual(cmd, self.ad["agy"].build_command("kisa istem", model="gemini-3.8-flash-high", effort="high"))


class ConductorDavranisi(unittest.TestCase):
    def test_hata_olsa_da_is_busy_kalkar_sef_error_olur(self):
        class Patlayan:
            name = "Patlayan"

            async def execute(self, *a, **k):
                raise RuntimeError("patladı")

        o = ConductorOrchestrator(conductor_key="claude", adapters={"claude": Patlayan(), "agy": Patlayan()})
        durumlar = []
        o.on_status_change_callback = lambda k, d: durumlar.append((k, d))
        with self.assertRaises(RuntimeError):
            asyncio.run(o.execute_objective("hedef"))
        self.assertFalse(o.is_busy)
        self.assertEqual(o.agent_statuses["claude"], AgentStatus.ERROR)
        self.assertIn(("claude", AgentStatus.ERROR), durumlar)

    def test_cwd_tum_cagrilara_gecer_gorev_running_olur(self):
        from sahte import create_fake_adapters

        gorunen_cwd, gorev_durumlari = [], []
        adaptorler = create_fake_adapters(["claude", "agy"], {"claude": "C", "agy": "A"}, ["agy"])
        for a in adaptorler.values():
            ilk = a.execute

            async def sar(*args, _ilk=ilk, **kw):
                gorunen_cwd.append(kw.get("cwd"))
                return await _ilk(*args, **kw)

            a.execute = sar
        o = ConductorOrchestrator(conductor_key="claude", worker_keys=["agy"], cwd="C:\\x", adapters=adaptorler)
        o.on_status_change_callback = lambda k, d: gorev_durumlari.append([t.status for t in o.current_plan])
        asyncio.run(o.execute_objective("hedef"))
        self.assertTrue(gorunen_cwd and all(c == "C:\\x" for c in gorunen_cwd), gorunen_cwd)
        self.assertEqual(len(gorunen_cwd), 4)  # plan + 2 işçi + sentez
        self.assertTrue(any(AgentStatus.RUNNING in d for d in gorev_durumlari))
        self.assertFalse(o.is_busy)

    def test_sef_icin_override_uygulanir(self):
        o = ConductorOrchestrator(conductor_key="claude", models_override={"claude": "opus"},
                                  efforts_override={"claude": "max"}, adapters={})
        self.assertEqual(o.conductor_model, "opus")
        self.assertEqual(o.conductor_effort, "max")


def satirlar(cikti: str):
    return [json.loads(s) for s in cikti.splitlines() if s.strip()]


class RunnerSozlesmesi(unittest.TestCase):
    def test_katalog(self):
        r = subprocess.run([sys.executable, RUNNER, "--katalog"], capture_output=True, text=True,
                           encoding="utf-8", env=ENV, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        olaylar = satirlar(r.stdout)
        self.assertEqual(len(olaylar), 1)
        k = olaylar[0]
        self.assertEqual(k["t"], "katalog")
        self.assertEqual(k["varsayilan_sef"], "claude")
        self.assertEqual(k["varsayilan_isciler"], ["agy", "codex", "muse"])
        self.assertEqual([s["anahtar"] for s in k["saglayicilar"]], ["claude", "agy", "codex", "muse"])
        self.assertEqual(k["gizli"], [])
        self.assertIs(k["bayat"], False)            # taze önbellek: keşif yok, bayat değil
        self.assertTrue(k["taranma"])
        for s in k["saglayicilar"]:
            self.assertEqual(set(s), {"anahtar", "ad", "ikon", "aciklama", "kurulu", "ozel", "modeller", "efforlar",
                                      "varsayilan_model", "varsayilan_effort", "taranma", "kaynak"})
            self.assertEqual(s["kaynak"], "canli")
            self.assertTrue(s["taranma"])
            self.assertIsInstance(s["kurulu"], bool)
            self.assertIs(s["ozel"], False)
            self.assertTrue(s["modeller"] and set(s["modeller"][0]) == {"id", "ad", "kademe"})

    def _sahte_calistir(self, **spec_ek):
        with tempfile.TemporaryDirectory() as klasor:
            spec = {"hedef": "Sahte hedef", "sef": "claude", "model": "haiku", "effort": "low",
                    "isciler": ["agy", "codex"], "modeller": {}, "eforlar": {}, "klasor": klasor}
            spec.update(spec_ek)
            yol = os.path.join(klasor, "spec.json")
            with open(yol, "w", encoding="utf-8") as f:
                json.dump(spec, f)
            return subprocess.run([sys.executable, RUNNER, "--calistir", yol, "--sahte"], capture_output=True,
                                  text=True, encoding="utf-8", env=ENV, timeout=60)

    def test_sahte_calistirma_sozlesme(self):
        r = self._sahte_calistir()
        self.assertEqual(r.returncode, 0, r.stderr)
        olaylar = satirlar(r.stdout)  # stdout'ta JSON dışı satır olursa burada patlar
        self.assertEqual(olaylar[0]["t"], "basladi")
        self.assertEqual(set(olaylar[0]), {"t", "sef", "model", "effort", "isciler", "klasor"})
        self.assertEqual(olaylar[-1]["t"], "bitti")
        self.assertEqual(set(olaylar[-1]["jeton"]), {"girdi", "cikti", "onbellek"})
        self.assertTrue(olaylar[-1]["sonuc"].startswith("Sahte sentez"))
        turler = {o["t"] for o in olaylar}
        self.assertEqual(turler, {"basladi", "ajan", "plan", "mesaj", "akim", "bitti"})
        for o in olaylar:
            if o["t"] == "ajan":
                self.assertEqual(set(o), {"t", "ajan", "durum"})
            elif o["t"] == "akim":
                self.assertEqual(set(o), {"t", "ajan", "metin"})
                self.assertNotIn("[dim", o["metin"])
            elif o["t"] == "mesaj":
                self.assertEqual(set(o), {"t", "id", "zaman", "gonderen", "alici", "tur", "ozet", "icerik",
                                          "girdi", "cikti", "sure", "gorev"})
            elif o["t"] == "plan":
                for g in o["gorevler"]:
                    self.assertEqual(set(g), {"id", "baslik", "isci", "talimat", "dosyalar", "durum", "jeton", "sure"})
        planlar = [o["gorevler"] for o in olaylar if o["t"] == "plan"]
        self.assertEqual([g["isci"] for g in planlar[0]], ["agy", "codex"])
        self.assertEqual([g["durum"] for g in planlar[-1]], ["FINISHED", "FINISHED"])
        self.assertTrue(any(g["durum"] == "RUNNING" for p in planlar for g in p))
        self.assertEqual([o["tur"] for o in olaylar if o["t"] == "mesaj"][:2], ["USER_INPUT", "CHIEF_PLAN"])
        self.assertEqual([o["tur"] for o in olaylar if o["t"] == "mesaj"][-1], "CHIEF_SYNTHESIS")
        # plan her değişimde değil yalnız değişince: ardışık iki aynı plan olmamalı
        for a, b in zip(planlar, planlar[1:]):
            self.assertNotEqual(a, b)

    def test_iscisiz_sef_kendi_isci_olur(self):
        r = self._sahte_calistir(isciler=[])
        self.assertEqual(r.returncode, 0, r.stderr)
        olaylar = satirlar(r.stdout)
        self.assertEqual(olaylar[0]["isciler"], ["claude"])
        self.assertEqual([g["isci"] for g in [o for o in olaylar if o["t"] == "plan"][0]["gorevler"]],
                         ["claude", "claude"])

    def test_dogrulama_hatalari(self):
        for ek, parca in (({"klasor": "C:\\yok\\boyle\\klasor"}, "klasör"), ({"sef": "yok"}, "şef"),
                          ({"isciler": ["x"]}, "işçi"), ({"hedef": "  "}, "Hedef"),
                          ({"model": "a&b"}, "model")):
            r = self._sahte_calistir(**ek)
            self.assertEqual(r.returncode, 1, ek)
            son = satirlar(r.stdout)[-1]
            self.assertEqual(son["t"], "hata", ek)
            self.assertIn(parca.lower(), son["mesaj"].lower(), ek)

    def test_iptal_surec_agacini_oldurur(self):
        with tempfile.TemporaryDirectory() as klasor:
            yol = os.path.join(klasor, "spec.json")
            with open(yol, "w", encoding="utf-8") as f:
                json.dump({"hedef": "iptal", "sef": "claude", "isciler": ["agy"], "klasor": klasor}, f)
            p = subprocess.Popen([sys.executable, RUNNER, "--calistir", yol, "--sahte"], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, encoding="utf-8", env=ENV)
            ilk = p.stdout.readline()  # "basladi" geldi: süreç çalışıyor
            self.assertEqual(json.loads(ilk)["t"], "basladi")
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
            bitis = time.time() + 10
            while p.poll() is None and time.time() < bitis:
                time.sleep(0.1)
            self.assertIsNotNone(p.poll(), "süreç öldürülemedi")
            p.stdout.close()
            p.stderr.close()


@unittest.skipUnless(sys.platform == "win32", "Windows süreç ağacı")
class ZamanAsimi(unittest.TestCase):
    def test_zaman_asimi_sureci_oldurur(self):
        from adapters.base import BaseCLIAdapter

        class Uyuyan(BaseCLIAdapter):
            def build_command(self, prompt, model=None, effort=None):
                return [sys.executable, "-c", "import time; time.sleep(60)"]

        a = Uyuyan("u", "Uyuyan", "python", "x")
        kod, cikti, sure = asyncio.run(a.execute("x", timeout=1))
        self.assertEqual(kod, -1)
        self.assertIn("Zaman aşımı", cikti)
        self.assertLess(sure, 15)

    def test_stdin_ve_cok_satirli_istem_oldugu_gibi_ulasir(self):
        from adapters.base import BaseCLIAdapter

        class Yankı(BaseCLIAdapter):
            def build_command(self, prompt, model=None, effort=None):
                return [sys.executable, "-X", "utf8", "-c", "import sys; sys.stdout.write(sys.stdin.read())"]

            def prepare(self, prompt, model=None, effort=None, cwd=None):
                return self.build_command(prompt), prompt.encode("utf-8"), []

        a = Yankı("y", "Yankı", "python", "x")
        istem = ZOR_ISTEM + "\n" + "x" * 300_000  # boru tamponunu aşan istem de kilitlenmesin
        kod, cikti, _ = asyncio.run(a.execute(istem, timeout=60))
        self.assertEqual(kod, 0)
        self.assertEqual(cikti.replace("\r\n", "\n"), istem)

    def test_stderr_sonuca_karismaz_ama_canli_cikti_ve_hatada_gorunur(self):
        from adapters.base import BaseCLIAdapter

        class Uyarili(BaseCLIAdapter):
            def __init__(self, kod, stdout_var):
                super().__init__("u", "Uyarılı", "python", "x")
                self.kod, self.stdout_var = kod, stdout_var

            def build_command(self, prompt, model=None, effort=None):
                betik = ("import sys; sys.stderr.write('UYARI' + chr(10)); "
                         + ("print('YANIT'); " if self.stdout_var else "") + "sys.exit(%d)" % self.kod)
                return [sys.executable, "-X", "utf8", "-c", betik]

        canli = []
        kod, cikti, _ = asyncio.run(Uyarili(0, True).execute("x", on_output=canli.append))
        self.assertEqual((kod, cikti.strip()), (0, "YANIT"))          # uyarı sonuca girmez
        self.assertTrue(any("UYARI" in p for p in canli))             # ama canlı çıktıda görünür
        kod, cikti, _ = asyncio.run(Uyarili(0, False).execute("x"))
        self.assertEqual((kod, cikti.strip()), (0, "UYARI"))          # stdout boşsa stderr sonuçtur
        kod, cikti, _ = asyncio.run(Uyarili(3, True).execute("x"))
        self.assertEqual(kod, 3)
        self.assertIn("YANIT", cikti)
        self.assertIn("UYARI", cikti)                                 # hata nedeni sonuca eklenir


if __name__ == "__main__":
    unittest.main(verbosity=2)
