"""Model keşfi testleri (hermetik: gerçek CLI çağrılmaz, gerçek .models_cache.json'a dokunulmaz).

    py -3 test_model_kesfi.py            (orkestra klasöründe)

Sahte CLI'lar geçici bir klasördeki .cmd dosyalarıdır (PATH'in başına konur); codex'in önbelleği CODEX_HOME ile,
model önbelleği MODELS_CACHE ile, ajan ayarı ORKESTRA_AJANLAR ile geçici dosyalara yönlendirilir.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

KLASOR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KLASOR)
_TEMEL = tempfile.mkdtemp(prefix="orkestra-kesif-test-")
os.environ["ORKESTRA_AJANLAR"] = os.path.join(_TEMEL, "yok", "ajanlar.json")
os.environ["MODELS_CACHE"] = os.path.join(_TEMEL, "varsayilan-onbellek.json")
os.environ["CODEX_HOME"] = os.path.join(_TEMEL, "codex-yok")

import model_discovery as md  # noqa: E402
import ozel_ajan  # noqa: E402

RUNNER = os.path.join(KLASOR, "runner.py")
PY = sys.executable

# ── Gerçek örnek çıktılar (11.2026, bu makineden) ─────────────────────────────────────────────
AGY_MODELS = (
    "gemini-4-argon-medium\tGemini 4 Argon (Medium)\n"
    "gemini-4-argon-high\tGemini 4 Argon (High)\n"
    "gemini-4-argon-low\tGemini 4 Argon (Low)\n"
    "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
    "gemini-3.8-flash-low\tGemini 3.8 Flash (Low)\n"
    "claude-opus-5-5-high\tClaude Opus 5.5 (High)\n"
    "claude-sonnet-5-5-low\tClaude Sonnet 5.5 (Low)\n"
    "gpt-oss-120b-medium\tGPT-OSS 120B (Medium)\n"
)
AGY_YARDIM = (
    "  --dangerously-skip-permissions  Auto-approve all tool permission requests without prompting\n"
    "  --effort                        Reasoning effort for the current CLI session (low|medium|high|xhigh|max)\n"
    "  --input-format                  Input format for print mode (text, stream-json)\n"
)
CLAUDE_MODEL = (
    "Current model: `Fable 5.2` (effort: xhigh)\n"
    "Usage: /model <name>. Available: sonnet, opus, haiku, fable, best, sonnet[1m], opus[1m], fable[1m], opusplan, "
    "default, or a full model ID.\n"
)
CLAUDE_EFFORT = "Current effort: xhigh\nUsage: /effort <low|medium|high|xhigh|max|auto>\n"
MUSE_YARDIM = (
    "      --reasoning-effort <EFFORT>\n"
    "          Meta reasoning effort: none|minimal|low|medium|high|xhigh|max|ultra\n"
    "          (default: high; alias: --effort)\n"
    "      --parallel-tool-calls\n"
)
# mimo models: UTF-8 uzun tire bozuk kodlanmış gelebiliyor ("â€”"); satır başındaki parça kimliktir.
MIMO_MODELS = (
    "mimo/mimo-auto â€” window 1M, compacts at 900K\n"
    "xiaomi/mimo-v2.6-flash â€” window 1.05M, compacts at 944K\n"
    "xiaomi/mimo-v2.6-pro â€” window 1.05M, compacts at 944K\n"
    "xiaomi/mimo-v2.6-pro-ultraspeed â€” window 1.05M, compacts at 944K\n"
)
CODEX_ONBELLEK = {
    "fetched_at": "2026-11-12T12:40:28Z", "etag": "x", "client_version": "1.0", "identity": "gizli",
    "models": [
        {"slug": "gpt-reserve", "display_name": "GPT-Reserve", "visibility": "hide", "priority": 1,
         "default_reasoning_level": "medium", "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"}]},
        {"slug": "gpt-5.6-terra", "display_name": "GPT-5.6-Terra", "visibility": "list", "priority": 5,
         "default_reasoning_level": "high",
         "supported_reasoning_levels": [{"effort": "low", "description": "x"}, {"effort": "medium"}, {"effort": "high"},
                                        {"effort": "xhigh"}, {"effort": "max"}, {"effort": "ultra"}]},
        {"slug": "gpt-6-luna", "display_name": "GPT-6-Luna", "visibility": "list", "priority": 2,
         "default_reasoning_level": "medium",
         "supported_reasoning_levels": ["low", "medium", "high", "xhigh", "max"]},          # düz string seviyeler
        {"slug": "gpt-5.6-luna", "visibility": "list", "priority": 9, "supported_reasoning_levels": []},   # ad yok
        {"slug": "codex-auto-review", "display_name": "Codex Auto Review", "visibility": "hide", "priority": 3,
         "supported_reasoning_levels": [{"effort": "low"}]},
        {"slug": "kotu id!", "visibility": "list", "priority": 0},                           # geçersiz kimlik: atlanır
    ],
}
ESKI_ADLAR = ("gpt-6-astra", "gpt-5.6-sol", "muse-spark", "gemini-3.", "claude-sonnet-4", "claude-opus-4", "o3-mini")


def eski_tarih(saat=7):
    return (datetime.now(timezone.utc) - timedelta(hours=saat)).isoformat(timespec="seconds")


class Ayristiricilar(unittest.TestCase):
    def test_agy_modelleri(self):
        m = md.agy_coz(AGY_MODELS)
        self.assertEqual([x["id"] for x in m][:3], ["gemini-4-argon-medium", "gemini-4-argon-high", "gemini-4-argon-low"])
        self.assertEqual(len(m), 8)
        self.assertEqual(m[1]["name"], "Gemini 4 Argon (High)")
        self.assertEqual(m[1]["tier"], "reasoning")                      # "high"
        self.assertEqual(next(x for x in m if x["id"] == "claude-sonnet-5-5-low")["tier"], "fast")

    def test_agy_baslik_ve_uyari_satirlari_model_degil(self):
        m = md.agy_coz("Fetching available models...\nWarning:\tbir uyarı\nError\n" + AGY_MODELS + "gemini-4-argon-low\tYinelenen\n")
        self.assertEqual(len(m), 8)                                      # başlık/uyarı yok, yineleme tek
        self.assertNotIn("Error", [x["id"] for x in m])

    def test_agy_sekmesiz_cikti_iki_bosluktan_bolunur(self):
        m = md.agy_coz("gemini-4-argon-high  Gemini 4 Argon (High)\n")
        self.assertEqual((m[0]["id"], m[0]["name"]), ("gemini-4-argon-high", "Gemini 4 Argon (High)"))

    def test_agy_seviyeleri_yardimdan(self):
        self.assertEqual(md.agy_effort_coz(AGY_YARDIM), ["low", "medium", "high", "xhigh", "max"])
        self.assertEqual(md.agy_effort_coz("bambaşka çıktı"), [])

    def test_claude_takma_adlari(self):
        m = md.claude_modeller_coz(CLAUDE_MODEL)
        self.assertEqual([x["id"] for x in m], ["sonnet", "opus", "haiku", "fable", "best", "sonnet[1m]", "opus[1m]",
                                                "fable[1m]", "opusplan", "default"])        # "or a full model ID" atıldı
        tier = {x["id"]: x["tier"] for x in m}
        self.assertEqual((tier["opus"], tier["haiku"], tier["sonnet"]), ("reasoning", "fast", "balanced"))
        self.assertEqual(next(x for x in m if x["id"] == "default")["name"], md.VARSAYILAN_AD)

    def test_claude_modeller_yoksa_bos(self):
        self.assertEqual(md.claude_modeller_coz("Permission allow rule ...\nbeklenmeyen çıktı"), [])

    def test_claude_seviyeleri(self):
        self.assertEqual(md.claude_effort_coz(CLAUDE_EFFORT), ["low", "medium", "high", "xhigh", "max", "auto"])
        self.assertEqual(md.claude_effort_coz("yok"), [])

    def test_codex_onbellegi(self):
        s = md.codex_coz(CODEX_ONBELLEK)
        self.assertEqual([m["id"] for m in s["models"]], ["gpt-6-luna", "gpt-5.6-terra", "gpt-5.6-luna"])   # priority sırası, hide ve kötü id yok
        self.assertEqual(s["default_model"], "gpt-6-luna")
        self.assertEqual(s["default_effort"], "medium")
        terra = next(m for m in s["models"] if m["id"] == "gpt-5.6-terra")
        luna6 = next(m for m in s["models"] if m["id"] == "gpt-6-luna")
        self.assertIn("ultra", terra["efforlar"])                        # modele özel seviye
        self.assertNotIn("ultra", luna6["efforlar"])
        self.assertEqual(luna6["efforlar"], ["low", "medium", "high", "xhigh", "max"])   # düz string seviyeler
        self.assertEqual(terra["name"], "GPT-5.6-Terra")
        self.assertEqual(next(m for m in s["models"] if m["id"] == "gpt-5.6-luna")["name"], "gpt-5.6-luna")   # ad yoksa kimlik
        self.assertEqual(s["efforts"], ["low", "medium", "high", "xhigh", "max", "ultra"])  # birleşim, kanonik sıra

    def test_codex_gecersiz_onbellek(self):
        self.assertIsNone(md.codex_coz({"models": []}))
        self.assertIsNone(md.codex_coz({"models": [{"slug": "a-1", "visibility": "hide"}]}))
        self.assertIsNone(md.codex_coz([1, 2]))
        self.assertIsNone(md.codex_coz({"models": "x"}))

    def test_muse_seviyeleri(self):
        seviyeler, varsayilan = md.muse_help_coz(MUSE_YARDIM)
        self.assertEqual(seviyeler, ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"])
        self.assertEqual(varsayilan, "high")
        self.assertEqual(md.muse_help_coz("hiçbir şey"), ([], None))

    def test_mimo_bozuk_kodlanmis_tire(self):
        m = md.liste_coz(MIMO_MODELS)
        self.assertEqual([x["id"] for x in m], ["mimo/mimo-auto", "xiaomi/mimo-v2.6-flash", "xiaomi/mimo-v2.6-pro",
                                                "xiaomi/mimo-v2.6-pro-ultraspeed"])
        self.assertTrue(all(x["tier"] == "special" for x in m))

    def test_liste_basliklari_model_degil(self):
        m = md.liste_coz("Performing one time database migration...\nWARNING: x\nError: y\n  xiaomi/mimo-v2.6-flash — w\n\n")
        self.assertEqual([x["id"] for x in m], ["xiaomi/mimo-v2.6-flash"])

    def test_temizle(self):
        self.assertEqual(md.temizle("\x1b[91mmodel-1\x1b[0m\r\nikinci\x00\x07\n"), "model-1\nikinci\n")


class YedekListe(unittest.TestCase):
    def test_hicbir_saglayicida_eski_ad_yok(self):
        for anahtar, g in md.FALLBACK_DATA.items():
            for m in g["models"]:
                for eski in ESKI_ADLAR:
                    self.assertNotIn(eski, m["id"], (anahtar, m))
        for anahtar in ("agy", "codex", "muse"):
            self.assertEqual([m["id"] for m in md.FALLBACK_DATA[anahtar]["models"]], ["default"])
        self.assertEqual([m["id"] for m in md.FALLBACK_DATA["claude"]["models"]],
                         ["sonnet", "opus", "haiku", "fable", "default"])
        self.assertTrue(all(g["default_model"] == "default" for g in md.FALLBACK_DATA.values()))
        self.assertEqual(md.FALLBACK_DATA["muse"]["models"][0]["name"], md.VARSAYILAN_AD)

    def test_kaynak_dosyalarinda_sabit_eski_model_adi_yok(self):
        for dosya in ("model_discovery.py", "config.py", "adapters/__init__.py", "adapters/agy_adapter.py",
                      "adapters/codex_adapter.py", "adapters/muse_adapter.py", "adapters/claude_adapter.py"):
            with open(os.path.join(KLASOR, dosya), encoding="utf-8") as f:
                metin = f.read()
            for eski in ESKI_ADLAR:
                self.assertNotIn(eski, metin, (dosya, eski))


class Onbellek(unittest.TestCase):
    def setUp(self):
        self.yol = os.path.join(tempfile.mkdtemp(dir=_TEMEL), "alt", "onbellek.json")
        self._env("MODELS_CACHE", self.yol)

    def _env(self, anahtar, deger):
        eski = os.environ.get(anahtar)
        os.environ[anahtar] = deger
        self.addCleanup(lambda: os.environ.__setitem__(anahtar, eski) if eski is not None else os.environ.pop(anahtar, None))

    def test_dosya_yoksa_yedek_ve_cli_calismaz(self):
        orijinal = md._calistir
        md._calistir = lambda *a, **k: (_ for _ in ()).throw(AssertionError("içe aktarmada/okumada CLI çalıştırılmamalı"))
        self.addCleanup(lambda: setattr(md, "_calistir", orijinal))
        v = md.load_cached_models()
        self.assertEqual(set(v), set(md.YERLESIK))
        self.assertTrue(all(g["kaynak"] == "yedek" and g["taranma"] is None for g in v.values()))
        import config                                                    # config de CLI'ya dokunmaz
        p = config.get_live_providers()
        self.assertEqual([m.id for m in p["agy"].models], ["default"])
        self.assertEqual((p["agy"].kaynak, p["agy"].taranma), ("yedek", None))
        self.assertIs(md.bayat(), True)                                  # hiç taranmamış: bayat

    def test_gecerli_girdiler_okunur_bozuklar_atilir(self):
        os.makedirs(os.path.dirname(self.yol))
        with open(self.yol, "w", encoding="utf-8") as f:
            json.dump({"agy": {"models": [{"id": "x-1", "name": "X 1", "tier": "fast", "efforlar": ["low", "kötü seviye!"]},
                                           {"id": "kötü id", "name": "?"}, "bozuk"],
                               "efforts": ["low", "BÜYÜK"], "default_model": "olmayan", "taranma": "tarih değil"},
                       "codex": {"models": []}, "muse": "düz metin", "claude": {"models": [{"id": "default"}]}}, f)
        veri, gecerli = md.cache_oku()
        self.assertTrue(gecerli)
        self.assertEqual(set(veri), {"agy", "claude"})                  # modelsiz/bozuk girdiler atıldı
        self.assertEqual(veri["agy"]["models"], [{"id": "x-1", "name": "X 1", "tier": "fast", "efforlar": ["low"]}])
        self.assertEqual((veri["agy"]["default_model"], veri["agy"]["taranma"], veri["agy"]["efforts"]), ("x-1", None, ["low"]))
        birlesik = md.load_cached_models()
        self.assertEqual(birlesik["codex"]["kaynak"], "yedek")           # önbellekte kullanılamayan: yedek
        self.assertEqual(birlesik["claude"]["efforts"], md.FALLBACK_DATA["claude"]["efforts"])   # eksik seviye listesi yedekten

    def test_bozuk_dosya_gecersiz(self):
        os.makedirs(os.path.dirname(self.yol))
        for icerik in ("{bozuk json", "[1, 2]"):
            with open(self.yol, "w", encoding="utf-8") as f:
                f.write(icerik)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(md.cache_oku(), ({}, False))

    def test_yaz_oku_atomik(self):
        veri = {k: dict(v, taranma=md.simdi_iso(), kaynak="canli") for k, v in md.FALLBACK_DATA.items()}
        self.assertTrue(md.save_cached_models(veri))
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.yol))), ["onbellek.json"])   # geçici dosya kalmadı
        okunan, gecerli = md.cache_oku()
        self.assertTrue(gecerli)
        self.assertEqual(okunan["claude"]["models"], md.load_cached_models()["claude"]["models"])
        self.assertIs(md.bayat(okunan), False)

    def test_ttl_ve_bayat(self):
        taze = dict(md.FALLBACK_DATA["claude"], taranma=md.simdi_iso(), kaynak="canli")
        self.assertIs(md._bayat_girdi(taze), False)
        self.assertIs(md._bayat_girdi(dict(taze, taranma=eski_tarih(5))), False)        # 6 saatten genç
        self.assertIs(md._bayat_girdi(dict(taze, taranma=eski_tarih(7))), True)          # 6 saatten eski
        self.assertIs(md._bayat_girdi(dict(taze, taranma=None)), True)
        self.assertIs(md._bayat_girdi(None), True)
        veri = {k: dict(v, taranma=md.simdi_iso(), kaynak="canli") for k, v in md.FALLBACK_DATA.items()}
        self.assertIs(md.bayat(veri), False)
        veri["muse"]["taranma"] = eski_tarih(8)
        self.assertIs(md.bayat(veri), True)                                              # biri bayatsa hepsi bayat sayılır
        self.assertEqual(md.en_eski_taranma(veri), veri["muse"]["taranma"])
        self.assertIsNone(md.en_eski_taranma({"a": {"taranma": None}}))


class SahteCli(unittest.TestCase):
    """PATH'in başına konan sahte agy/claude/muse (.cmd) ve CODEX_HOME'daki codex önbelleği."""

    def setUp(self):
        self.kok = tempfile.mkdtemp(dir=_TEMEL)
        self.bin = os.path.join(self.kok, "bin")
        self.sayac = os.path.join(self.kok, "sayac")
        for k in (self.bin, self.sayac, os.path.join(self.kok, "codex")):
            os.makedirs(k)
        self.yol = os.path.join(self.kok, "onbellek.json")
        self.ajanlar = os.path.join(self.kok, "ajanlar.json")
        self._env("MODELS_CACHE", self.yol)
        self._env("ORKESTRA_AJANLAR", self.ajanlar)
        self._env("CODEX_HOME", os.path.join(self.kok, "codex"))
        self._env("PATH", self.bin + os.pathsep + os.environ["PATH"])
        self.sinir = md.KESIF_SINIRI_SN
        self.addCleanup(lambda: setattr(md, "KESIF_SINIRI_SN", self.sinir))
        self.yaz_cli_hepsi()
        self.yaz_codex()

    def _env(self, anahtar, deger):
        eski = os.environ.get(anahtar)
        os.environ[anahtar] = deger
        self.addCleanup(lambda: os.environ.__setitem__(anahtar, eski) if eski is not None else os.environ.pop(anahtar, None))

    def _metin(self, ad, icerik):
        yol = os.path.join(self.kok, ad)
        with open(yol, "w", encoding="utf-8", newline="") as f:
            f.write(icerik)
        return yol

    def _cmd(self, ad, govde):
        with open(os.path.join(self.bin, ad), "w", encoding="utf-8", newline="") as f:
            f.write("@echo off\r\n" + govde.replace("\n", "\r\n") + "\r\n")

    def yaz_cli_hepsi(self, gecikme=0, agy_hata=False, claude_hata=False, muse_gecikme=0):
        bekle = lambda sn: ("ping -n %d 127.0.0.1 >nul\n" % (sn + 1)) if sn else ""
        agy_m, agy_y = self._metin("agy_models.txt", AGY_MODELS), self._metin("agy_help.txt", AGY_YARDIM)
        c_m, c_e = self._metin("claude_model.txt", CLAUDE_MODEL), self._metin("claude_effort.txt", CLAUDE_EFFORT)
        mu = self._metin("muse_help.txt", MUSE_YARDIM)
        sy = lambda ad: os.path.join(self.sayac, ad)          # çağrı başına ayrı sayaç dosyası: paralel çağrılar yarışmasın
        sayac = lambda ad: '>>"%s" echo x' % sy(ad)
        agy_cikti = "exit /b 1" if agy_hata else 'type "%s"' % agy_m
        claude_cikti = "exit /b 1" if claude_hata else 'type "%s"' % c_m
        self._cmd("agy.cmd", "\n".join([
            'if "%~1"=="models" goto m', 'if "%~1"=="--help" goto h', "exit /b 1",
            ":m", sayac("agy_models.txt"), bekle(gecikme) + agy_cikti, "exit /b 0",
            ":h", sayac("agy_help.txt"), 'type "%s" 1>&2' % agy_y, "exit /b 0"]))
        self._cmd("claude.cmd", "\n".join([
            'if "%~2"=="/model" goto m', 'if "%~2"=="/effort" goto e', "exit /b 1",
            ":m", sayac("claude_model.txt"), bekle(gecikme) + claude_cikti, "exit /b 0",
            ":e", sayac("claude_effort.txt"), 'type "%s"' % c_e, "exit /b 0"]))
        self._cmd("muse.cmd", "\n".join([sayac("muse.txt"), bekle(muse_gecikme or gecikme) + 'type "%s"' % mu, "exit /b 0"]))

    def yaz_codex(self, ham=None):
        with open(os.path.join(self.kok, "codex", "models_cache.json"), "w", encoding="utf-8") as f:
            json.dump(CODEX_ONBELLEK if ham is None else ham, f)

    def cagri(self, ad):
        """Sahte CLI'nın kaç kez çağrıldığı (ad.txt ve ad_*.txt sayaç dosyalarındaki satırlar)."""
        toplam = 0
        for dosya in os.listdir(self.sayac):
            if dosya == ad + ".txt" or dosya.startswith(ad + "_"):
                with open(os.path.join(self.sayac, dosya), encoding="utf-8") as f:
                    toplam += len([x for x in f.read().splitlines() if x.strip()])
        return toplam

    def onbellek(self):
        return md.cache_oku()[0]

    # ── keşif ──
    def test_hepsi_canli_kesfedilir_ve_yazilir(self):
        v = md.sync_all_models(force=True)
        for k in md.YERLESIK:
            self.assertEqual(v[k]["kaynak"], "canli", k)
            self.assertTrue(v[k]["taranma"], k)
        self.assertEqual([m["id"] for m in v["agy"]["models"]][:2], ["gemini-4-argon-medium", "gemini-4-argon-high"])
        self.assertEqual((v["agy"]["default_model"], v["agy"]["default_effort"]), ("gemini-4-argon-medium", "high"))
        self.assertEqual(v["agy"]["efforts"], ["low", "medium", "high", "xhigh", "max"])
        self.assertEqual((v["claude"]["default_model"], v["claude"]["default_effort"]), ("default", "high"))
        self.assertIn("fable", [m["id"] for m in v["claude"]["models"]])
        self.assertEqual([m["id"] for m in v["codex"]["models"]], ["gpt-6-luna", "gpt-5.6-terra", "gpt-5.6-luna"])
        self.assertEqual(v["codex"]["default_model"], "gpt-6-luna")
        self.assertEqual([m["id"] for m in v["muse"]["models"]], ["default"])
        self.assertIn("ultra", v["muse"]["efforts"])
        self.assertEqual(v["muse"]["default_effort"], "high")
        self.assertEqual(self.onbellek()["agy"]["kaynak"], "canli")                     # dosyaya yazıldı
        self.assertIs(md.bayat(), False)

    def test_kaynaklar_paralel_calisir(self):
        self.yaz_cli_hepsi(gecikme=3)                                                   # agy, claude, muse: her biri 3 sn
        t0 = time.monotonic()
        md.sync_all_models(force=True)
        gecen = time.monotonic() - t0
        self.assertLess(gecen, 7.0, "ardışık olsaydı en az 9 sn sürerdi: %.1f sn" % gecen)
        self.assertEqual(self.onbellek()["muse"]["kaynak"], "canli")

    def test_takilan_kaynak_digerlerini_geciktirmez_ve_oldurulur(self):
        md.KESIF_SINIRI_SN = 2
        self.yaz_cli_hepsi(muse_gecikme=20)                                              # muse 20 sn asılı
        t0 = time.monotonic()
        with contextlib.redirect_stderr(io.StringIO()) as hata:
            v = md.sync_all_models(force=True)
        gecen = time.monotonic() - t0
        self.assertLess(gecen, 12.0, "%.1f sn" % gecen)
        self.assertIn("muse", hata.getvalue())
        self.assertEqual((v["agy"]["kaynak"], v["claude"]["kaynak"], v["codex"]["kaynak"]), ("canli", "canli", "canli"))
        self.assertEqual(v["muse"]["kaynak"], "yedek")                                   # önceki veri yok: küçük yedek

    def test_zaman_asimi_onceki_iyi_veriyi_korur(self):
        md.KESIF_SINIRI_SN = 2
        eski = {"models": [{"id": "default", "name": "x", "tier": "balanced"}, {"id": "muse-eski-1", "name": "Eski", "tier": "fast"}],
                "efforts": ["low", "high"], "default_model": "muse-eski-1", "default_effort": "high",
                "taranma": eski_tarih(10), "kaynak": "canli"}
        md.save_cached_models({"muse": eski})
        self.yaz_cli_hepsi(muse_gecikme=20)
        with contextlib.redirect_stderr(io.StringIO()):
            md.sync_all_models(force=True)
        m = self.onbellek()["muse"]
        self.assertEqual([x["id"] for x in m["models"]], ["default", "muse-eski-1"])      # ezilmedi
        self.assertEqual((m["kaynak"], m["taranma"]), ("onbellek", eski["taranma"]))
        self.assertIs(md.bayat(), True)

    def test_basarisiz_kaynak_onceki_iyi_veriyi_korur(self):
        md.sync_all_models(force=True)                                                   # iyi veri
        once = self.onbellek()["agy"]
        self.yaz_cli_hepsi(agy_hata=True)                                                # agy models artık hata veriyor
        with contextlib.redirect_stderr(io.StringIO()) as hata:
            md.sync_all_models(force=True)
        agy = self.onbellek()["agy"]
        self.assertEqual(agy["models"], once["models"])                                  # boş listeyle ezilmedi
        self.assertEqual((agy["kaynak"], agy["taranma"]), ("onbellek", once["taranma"]))
        self.assertIn("agy", hata.getvalue())
        self.assertEqual(self.onbellek()["claude"]["kaynak"], "canli")                   # ötekiler yenilendi

    def test_codex_dosyasi_yoksa_ya_bozuksa_uydurma_model_yok(self):
        os.remove(os.path.join(self.kok, "codex", "models_cache.json"))
        with contextlib.redirect_stderr(io.StringIO()):
            v = md.sync_all_models(force=True)
        self.assertEqual((v["codex"]["kaynak"], [m["id"] for m in v["codex"]["models"]]), ("yedek", ["default"]))
        with open(os.path.join(self.kok, "codex", "models_cache.json"), "w") as f:
            f.write("{bozuk")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(md.kesfet_codex())

    def test_kesfet_fonksiyonlari_basarisizsa_none(self):
        self._env("PATH", self.kok)                                                       # hiçbir CLI bulunmaz
        with contextlib.redirect_stderr(io.StringIO()) as hata:
            self.assertIsNone(md.kesfet_agy())
            self.assertIsNone(md.kesfet_claude())
            self.assertIsNone(md.kesfet_muse())
        self.assertIn("bulunamadı", hata.getvalue())

    def test_force_false_yalniz_bayat_ya_da_eksikleri_tazeler(self):
        taze = lambda g: dict(g, taranma=md.simdi_iso(), kaynak="canli")
        veri = {k: taze(v) for k, v in md.FALLBACK_DATA.items()}
        veri["agy"]["taranma"] = eski_tarih(8)                                            # yalnız agy bayat
        md.save_cached_models(veri)
        md.sync_all_models(force=False)
        self.assertEqual((self.cagri("agy"), self.cagri("claude"), self.cagri("muse")), (2, 0, 0))   # agy: models + --help
        self.assertEqual(self.onbellek()["agy"]["kaynak"], "canli")
        self.assertEqual(self.onbellek()["claude"]["models"][0]["id"], "sonnet")          # taze olana dokunulmadı
        md.sync_all_models(force=False)                                                   # artık hepsi taze: keşif yok
        self.assertEqual(self.cagri("agy"), 2)
        md.sync_all_models(force=True)                                                    # zorla: hepsi
        self.assertEqual((self.cagri("agy"), self.cagri("claude"), self.cagri("muse")), (4, 2, 1))

    # ── runner --katalog ──
    def runner(self, *arg):
        r = subprocess.run([PY, RUNNER, *arg], capture_output=True, text=True, encoding="utf-8",
                           env=dict(os.environ, PYTHONUTF8="1"), timeout=120)
        return r.returncode, [json.loads(s) for s in r.stdout.splitlines() if s.strip()], r.stderr

    def test_runner_dosya_yokken_kesfeder_varken_kesfetmez(self):
        self.assertFalse(os.path.exists(self.yol))
        kod, o, _ = self.runner("--katalog")
        self.assertEqual((kod, len(o)), (0, 1))
        k = o[0]
        self.assertEqual((self.cagri("agy"), self.cagri("claude"), self.cagri("muse")), (2, 2, 1))   # keşif yapıldı
        self.assertTrue(os.path.exists(self.yol))                                          # ve yazıldı
        self.assertIs(k["bayat"], False)
        self.assertTrue(k["taranma"])
        saglayici = {s["anahtar"]: s for s in k["saglayicilar"]}
        self.assertEqual({s["kaynak"] for s in saglayici.values()}, {"canli"})
        self.assertEqual(saglayici["agy"]["varsayilan_model"], "gemini-4-argon-medium")
        self.assertEqual(saglayici["codex"]["varsayilan_model"], "gpt-6-luna")
        terra = next(m for m in saglayici["codex"]["modeller"] if m["id"] == "gpt-5.6-terra")
        self.assertEqual(terra["efforlar"], ["low", "medium", "high", "xhigh", "max", "ultra"])    # modele özel
        self.assertNotIn("efforlar", next(m for m in saglayici["agy"]["modeller"]))               # yoksa alan yok
        self.assertEqual(saglayici["claude"]["varsayilan_model"], "default")
        # dosya varken: olduğu gibi okunur, keşif yok
        kod, o, _ = self.runner("--katalog")
        self.assertEqual(kod, 0)
        self.assertEqual((self.cagri("agy"), self.cagri("claude"), self.cagri("muse")), (2, 2, 1))

    def test_runner_tara_ve_tazele_bayat(self):
        self.runner("--katalog")
        self.runner("--katalog", "--tazele-bayat")                                         # hepsi taze: keşif yok
        self.assertEqual(self.cagri("agy"), 2)
        veri = self.onbellek()
        veri["agy"]["taranma"] = eski_tarih(9)
        md.save_cached_models(veri)
        kod, o, _ = self.runner("--katalog")                                                # dosya var: okur, bayat bildirir
        self.assertEqual(self.cagri("agy"), 2)
        self.assertIs(o[0]["bayat"], True)
        self.assertEqual(o[0]["taranma"], veri["agy"]["taranma"])                           # en eski tarama
        kod, o, _ = self.runner("--katalog", "--tazele-bayat")                              # yalnız bayat olan tazelenir
        self.assertEqual((self.cagri("agy"), self.cagri("claude")), (4, 2))
        self.assertIs(o[0]["bayat"], False)
        kod, o, _ = self.runner("--katalog", "--tara")                                       # zorla: hepsi
        self.assertEqual((self.cagri("agy"), self.cagri("claude"), self.cagri("muse")), (6, 4, 2))

    def test_runner_katalogda_hicbir_kaynak_yoksa_yedekle_calisir(self):
        self._env("PATH", self.kok)                                                          # CLI yok
        os.remove(os.path.join(self.kok, "codex", "models_cache.json"))
        kod, o, _ = self.runner("--katalog")
        self.assertEqual(kod, 0)
        self.assertEqual({s["kaynak"] for s in o[0]["saglayicilar"]}, {"yedek"})
        self.assertIs(o[0]["bayat"], True)
        self.assertIsNone(o[0]["taranma"])
        self.assertTrue(os.path.exists(self.yol))                                            # sonraki çağrı yeniden 60 sn denemesin

    # ── özel ajan (model_komutu) ──
    def ozel(self, **ek):
        taban = {"anahtar": "deneme", "ad": "Deneme", "komut": PY, "argumanlar": ["-c", "print(1)", "{istem_dosyasi}"],
                 "istem": "dosya", "model_komutu": ["-c", "print('a/b-1 - pencere 1M'); print('Uyari:'); print('Hata olustu'); print('c:d[2]')"],
                 "modeller": ["elle-1"], "efforlar": ["high"], "varsayilan_model": "", "varsayilan_effort": "high"}
        taban.update(ek)
        return taban

    def test_ozel_ajan_model_komutu_ile_kesfedilir(self):
        ozel_ajan.ekle(self.ozel())
        v = md.sync_all_models(force=True)
        g = v["ozel:deneme"]
        self.assertEqual([m["id"] for m in g["models"]], ["a/b-1", "c:d[2]"])                # başlık/uyarı satırları model değil
        self.assertEqual((g["kaynak"], g["default_model"], g["default_effort"]), ("canli", "a/b-1", "high"))
        import config
        p = config.get_live_providers()["deneme"]
        self.assertEqual([m.id for m in p.models], ["a/b-1", "c:d[2]", "elle-1"])            # canlı + elle eklenen
        self.assertEqual((p.kaynak, p.default_model), ("canli", "a/b-1"))
        kod, o, _ = self.runner("--katalog")
        s = next(x for x in o[0]["saglayicilar"] if x["anahtar"] == "deneme")
        self.assertEqual((s["kaynak"], [m["id"] for m in s["modeller"]]), ("canli", ["a/b-1", "c:d[2]", "elle-1"]))
        self.assertIs(s["ozel"], True)

    def test_ozel_ajan_komutsuz_elle_ve_silinince_onbellekten_dusar(self):
        ozel_ajan.ekle(self.ozel(anahtar="elle", model_komutu=[]))
        ozel_ajan.ekle(self.ozel())
        v = md.sync_all_models(force=True)
        self.assertNotIn("ozel:elle", v)                                                      # komutsuz: keşif yok
        import config
        self.assertEqual(config.get_live_providers()["elle"].kaynak, "elle")
        self.assertEqual([m.id for m in config.get_live_providers()["elle"].models], ["elle-1"])
        ozel_ajan.sil("deneme")
        md.sync_all_models(force=False)
        self.assertNotIn("ozel:deneme", self.onbellek())                                      # silinen ajanın girdisi atıldı

    def test_ozel_ajan_komutu_basarisizsa_onceki_liste_kalir(self):
        ozel_ajan.ekle(self.ozel())
        md.sync_all_models(force=True)
        ajanlar = ozel_ajan.yukle()
        ajanlar["ozel"][0]["model_komutu"] = ["-c", "import sys; sys.exit(3)"]
        ozel_ajan.kaydet(ajanlar)
        with contextlib.redirect_stderr(io.StringIO()):
            md.sync_all_models(force=True)
        g = self.onbellek()["ozel:deneme"]
        self.assertEqual(([m["id"] for m in g["models"]], g["kaynak"]), (["a/b-1", "c:d[2]"], "onbellek"))

    def test_ozel_ajan_bayat_hesabina_girer(self):
        ozel_ajan.ekle(self.ozel())
        veri = {k: dict(v, taranma=md.simdi_iso(), kaynak="canli") for k, v in md.FALLBACK_DATA.items()}
        md.save_cached_models(veri)
        self.assertIs(md.bayat(), True)                                                       # ozel:deneme hiç taranmamış


class ModelKomutuDogrulama(unittest.TestCase):
    def ajan(self, **ek):
        taban = {"anahtar": "deneme", "ad": "Deneme", "komut": PY, "argumanlar": ["x", "{istem_dosyasi}"], "istem": "dosya"}
        taban.update(ek)
        return taban

    def hata(self, parca, **ek):
        with self.assertRaises(ValueError) as c:
            ozel_ajan.dogrula_ajan(self.ajan(**ek))
        self.assertIn(parca.lower(), str(c.exception).lower())

    def test_gecerli_ve_varsayilan_bos(self):
        self.assertEqual(ozel_ajan.dogrula_ajan(self.ajan())["model_komutu"], [])
        self.assertEqual(ozel_ajan.dogrula_ajan(self.ajan(model_komutu=["models"]))["model_komutu"], ["models"])
        self.assertEqual(ozel_ajan.dogrula_ajan(self.ajan(model_komutu=None))["model_komutu"], [])

    def test_gecersizler(self):
        self.hata("liste", model_komutu="models")
        self.hata("en çok 10", model_komutu=["a"] * 11)
        self.hata("metin", model_komutu=[1])
        self.hata("en çok 200", model_komutu=["x" * 201])
        self.hata("satır sonu", model_komutu=["a\nb"])
        self.hata("satır sonu", model_komutu=["a\x00b"])

    def test_mimo_on_ayari_model_komutu_tasir(self):
        a = ozel_ajan.dogrula_ajan(ozel_ajan.MIMO_ONAYARI, kurulu_denetle=False)
        self.assertEqual(a["model_komutu"], ["models"])


class AdaptorlerDefaultModel(unittest.TestCase):
    def test_default_model_icin_model_bayragi_eklenmez(self):
        from adapters import create_adapters
        ad = create_adapters()
        for k in ("claude", "agy", "codex", "muse"):
            self.assertEqual(ad[k].default_model, "default", k)
        with tempfile.TemporaryDirectory() as klasor:
            for k, bayrak in (("claude", "--model"), ("agy", "--model"), ("codex", "-m"), ("muse", "--model")):
                cmd, _, temp = ad[k].prepare("x", cwd=klasor)
                for t in temp:
                    os.remove(t)
                self.assertNotIn(bayrak, cmd, k)
                cmd, _, temp = ad[k].prepare("x", model="gercek-model-1", cwd=klasor)
                for t in temp:
                    os.remove(t)
                self.assertEqual(cmd[cmd.index(bayrak) + 1], "gercek-model-1", k)

    def test_agy_xhigh_ve_max_seviyesi_gecer(self):
        from adapters import create_adapters
        for efor in ("xhigh", "max"):
            cmd, _, _ = create_adapters()["agy"].prepare("x", effort=efor)
            self.assertEqual(cmd[cmd.index("--effort") + 1], efor)
        cmd, _, _ = create_adapters()["agy"].prepare("x", effort="ultra")
        self.assertNotIn("--effort", cmd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
