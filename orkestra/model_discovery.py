"""
Canlı model ve akıl yürütme seviyesi keşfi.

Model listeleri SABİT KODLANMAZ: CLI'ların kendi kaynaklarından okunur ve önbelleğe yazılır.

  agy     `agy models` (id<TAB>ad) + `agy --help`'ten --effort seviyeleri
  claude  `claude -p /model` ("Available: ..." takma adları, CLI için hep en güncele işaret eder) ve
          `claude -p /effort`
  codex   ~/.codex/models_cache.json (codex'in kendi, hesabın gerçek listesi; yalnız visibility == "list"),
          modele özel seviyelerle (CODEX_HOME ile değişir)
  muse    model listeleyen komut yok: yalnız "default" (CLI'nin kendi varsayılanı); seviyeler
          `muse exec --help`'ten
  özel    ajanın `model_komutu` alanı (ör. mimo.exe models): satırın ilk boşluklu parçası model kimliğidir

Önbellek (`.models_cache.json`, MODELS_CACHE ile değişir), sağlayıcı başına:
  {"models": [{"id","name","tier","efforlar"?}], "efforts": [...], "default_model", "default_effort",
   "taranma": "<ISO UTC>" | null, "kaynak": "canli" | "onbellek" | "yedek" | "elle"}
  canli: şimdi CLI'dan okundu; onbellek: tazeleme başarısız oldu, önceki iyi veri korundu (taranma eski kalır);
  yedek: hiç okunamadı, küçük yedek liste (taranma null: her zaman bayat). Özel ajanlar "ozel:<anahtar>" anahtarıyla.

`sync_all_models(force=False)` yalnız eksik/bayat (TTL_SN'den eski) sağlayıcıları, `force=True` hepsini PARALEL tazeler;
bir kaynak başarısız olursa önceki iyi veri asla boş listeyle ezilmez. İçe aktarma ve `load_cached_models()` ağa/CLI'ya
dokunmaz.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

TTL_SN = 6 * 3600           # önbellek bu süreden eskiyse bayat
KESIF_SINIRI_SN = 60        # kaynak başına (alt süreç) en çok süre
YERLESIK = ("claude", "agy", "codex", "muse")
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/\[\]-]{1,80}$")
EFFORT_RE = re.compile(r"^[a-z0-9_-]{1,20}$")
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
VARSAYILAN_AD = "CLI varsayılanı"
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
# Orkestra bir Claude Code oturumundan açıldıysa bunlar alt claude'u o oturuma bağlar (panelin ork_ortam'ı gibi).
CLAUDE_TEMIZLE = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_SSE_PORT",
                  "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
KONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

# Önbellek yolu: ortam değişkeni her çağrıda okunur (testler ve panel sonradan değiştirebilsin).
CACHE_FILE = os.environ.get("MODELS_CACHE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".models_cache.json")


def cache_yolu() -> str:
    return os.environ.get("MODELS_CACHE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".models_cache.json")


# Hiçbir sağlayıcıda uydurma/eski model adı yok: keşif hiç çalışmadıysa (CLI yok, önbellek yok) görünen yedek.
# claude'un takma adları CLI'nin kendisinin kabul ettiği adlardır (hep en güncele işaret eder); ötekilerde yalnız
# "default" (CLI'nin kendi varsayılanı: adaptör --model eklemez).
def _yedek_model(mid: str, ad: Optional[str] = None, tier: str = "balanced") -> dict:
    return {"id": mid, "name": ad or VARSAYILAN_AD, "tier": tier}


FALLBACK_DATA: Dict[str, dict] = {
    "claude": {
        "models": [
            {"id": "sonnet", "name": "Claude Sonnet", "tier": "balanced"},
            {"id": "opus", "name": "Claude Opus", "tier": "reasoning"},
            {"id": "haiku", "name": "Claude Haiku", "tier": "fast"},
            {"id": "fable", "name": "Claude Fable", "tier": "balanced"},
            _yedek_model("default"),
        ],
        "efforts": list(CLAUDE_EFFORTS),
        "default_model": "default",
        "default_effort": "high",
    },
    "agy": {
        "models": [_yedek_model("default")],
        "efforts": ["low", "medium", "high"],
        "default_model": "default",
        "default_effort": "high",
    },
    "codex": {
        "models": [_yedek_model("default", tier="reasoning")],
        "efforts": ["low", "medium", "high", "xhigh"],
        "default_model": "default",
        "default_effort": "medium",
    },
    "muse": {
        "models": [_yedek_model("default")],
        "efforts": ["low", "medium", "high", "xhigh", "max"],
        "default_model": "default",
        "default_effort": "high",
    },
}


class KesifHatasi(Exception):
    """Bir kaynak okunamadı (mesaj stderr'e yazılır; önceki iyi veri korunur)."""


# ── Küçük yardımcılar ──────────────────────────────────────────────────────────────────────────

def simdi_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _zaman(iso) -> Optional[datetime]:
    try:
        z = datetime.fromisoformat(str(iso))
        return z if z.tzinfo else z.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def temizle(metin: str) -> str:
    """ANSI kaçışları ve denetim karakterleri (satır sonu ve sekme hariç) atılır."""
    metin = ANSI.sub("", metin or "").replace("\r\n", "\n").replace("\r", "\n")
    return KONTROL.sub("", metin)


def uyari(metin: str) -> None:
    print("model_discovery: " + metin, file=sys.stderr)


def _bul(*adaylar: str) -> Optional[str]:
    """PATH'te çözülebilen ilk program (ad) ya da mevcut dosya yolu."""
    for a in adaylar:
        yol = shutil.which(a)
        if yol:
            return yol
        if os.path.isfile(a):
            return a
    return None


def _agaci_oldur(pid: int) -> None:
    """Süreci ve altındakileri öldürür (.cmd kabuğunun altındaki node/exe de ölsün)."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True,
                           creationflags=CREATE_NO_WINDOW, timeout=30)
        else:
            os.kill(pid, 9)
    except Exception:
        pass


def _calistir(cmd: List[str], zaman: Optional[float] = None, env: Optional[dict] = None) -> Tuple[int, str, str]:
    """Komutu kabuksuz çalıştırır; (çıkış kodu, stdout, stderr), ikisi de temizlenmiş. Süre aşılırsa süreç ağacı
    öldürülür ve KesifHatasi atılır. Boş klasörde çalışır (bir projenin ayarı karışmasın)."""
    zaman = zaman or KESIF_SINIRI_SN
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         cwd=tempfile.gettempdir(), env=env, creationflags=CREATE_NO_WINDOW)
    try:
        out, err = p.communicate(timeout=zaman)
    except subprocess.TimeoutExpired:
        _agaci_oldur(p.pid)
        try:
            p.communicate(timeout=5)
        except Exception:
            pass
        raise KesifHatasi("%s %d saniyede bitmedi" % (os.path.basename(cmd[0]), zaman))
    except OSError as e:
        raise KesifHatasi("%s çalıştırılamadı: %s" % (cmd[0], e))
    dec = lambda b: temizle(b.decode("utf-8", errors="replace"))
    return p.returncode, dec(out), dec(err)


def _ilk_satir(*metinler: str) -> str:
    return next((s.strip() for m in metinler for s in (m or "").splitlines() if s.strip()), "")


def _kimlik_gibi(t: str) -> bool:
    """Model kimliğine benziyor mu: regex'e uyar, '-', '.', '/', ':', '_' ya da rakam içerir ve noktalama ile bitmez.
    Listeleyen komutların başlık/uyarı satırları ("Fetching ...", "Error:", "Performing ...") model sayılmasın."""
    return bool(MODEL_RE.match(t)) and not t.endswith((":", ".")) and re.search(r"[-./:_0-9]", t) is not None


def _model(mid: str, ad: Optional[str] = None, tier: str = "balanced", efforlar: Optional[List[str]] = None) -> dict:
    m = {"id": mid, "name": ad or mid, "tier": tier}
    if efforlar:
        m["efforlar"] = list(efforlar)
    return m


def _girdi(models: List[dict], efforts: List[str], default_model: str, default_effort: str) -> dict:
    """Canlı okunmuş sağlayıcı girdisi."""
    return {"models": models, "efforts": efforts, "default_model": default_model, "default_effort": default_effort,
            "taranma": simdi_iso(), "kaynak": "canli"}


def _siralı_benzersiz(liste) -> List[str]:
    cikti: List[str] = []
    for x in liste:
        if x not in cikti:
            cikti.append(x)
    return cikti


# ── Ayrıştırıcılar (saf fonksiyonlar; testlerde gerçek örnek çıktılarla sınanır) ─────────────────

def agy_coz(metin: str) -> List[dict]:
    """`agy models`: her satır `id<TAB>ad` (sekme yoksa 2+ boşluk). Kimliği geçersiz satırlar atılır."""
    modeller: List[dict] = []
    gorulen = set()
    for satir in temizle(metin).splitlines():
        parca = re.split(r"\t+|\s{2,}", satir.strip(), maxsplit=1)
        mid = parca[0].strip()
        if not _kimlik_gibi(mid) or mid in gorulen:
            continue
        gorulen.add(mid)
        ad = parca[1].strip() if len(parca) > 1 and parca[1].strip() else mid
        tier = "reasoning" if any(x in mid for x in ("pro", "opus", "high")) else "fast"
        modeller.append(_model(mid, ad, tier))
    return modeller


def agy_effort_coz(metin: str) -> List[str]:
    """`agy --help`: "--effort ... (low|medium|high|xhigh|max)"."""
    m = re.search(r"--effort\b[^\n]*\(([a-z0-9_|-]+)\)", temizle(metin))
    return [e for e in (m.group(1).split("|") if m else []) if EFFORT_RE.match(e)]


def claude_modeller_coz(metin: str) -> List[dict]:
    """`claude -p /model`: "Usage: /model <name>. Available: sonnet, opus, ..., or a full model ID."""
    m = re.search(r"Available:\s*([^\n]+)", temizle(metin))
    modeller: List[dict] = []
    for parca in (m.group(1) if m else "").split(","):
        mid = parca.strip().rstrip(".").strip()
        if not mid or mid.lower().startswith("or ") or not MODEL_RE.match(mid) or any(x["id"] == mid for x in modeller):
            continue
        if mid == "default":
            modeller.append(_model(mid, VARSAYILAN_AD))
            continue
        tier = "reasoning" if ("opus" in mid or "thinking" in mid) else ("fast" if "haiku" in mid else "balanced")
        modeller.append(_model(mid, "Claude %s" % mid.capitalize(), tier))
    return modeller


def claude_effort_coz(metin: str) -> List[str]:
    """`claude -p /effort`: "/effort <low|medium|high|xhigh|max>"."""
    m = re.search(r"/effort\s*<([^>]+)>", temizle(metin))
    return [e for e in _siralı_benzersiz(x.strip() for x in (m.group(1).split("|") if m else [])) if EFFORT_RE.match(e)]


def _seviye(oge) -> Optional[str]:
    s = oge.get("effort") if isinstance(oge, dict) else oge
    return s if isinstance(s, str) and EFFORT_RE.match(s) else None


def codex_coz(ham) -> Optional[dict]:
    """codex'in models_cache.json içeriği (dict): yalnız visibility == "list" modeller, `priority` küçük olan önce,
    modele özel seviyelerle. Geçerli model yoksa None."""
    if not isinstance(ham, dict) or not isinstance(ham.get("models"), list):
        return None
    adaylar = []
    for sira, m in enumerate(ham["models"]):
        if not isinstance(m, dict) or m.get("visibility") != "list":
            continue
        mid = m.get("slug") or m.get("id")
        if not isinstance(mid, str) or not MODEL_RE.match(mid):
            continue
        oncelik = m.get("priority") if isinstance(m.get("priority"), (int, float)) and not isinstance(m.get("priority"), bool) else 10 ** 6
        seviyeler = _siralı_benzersiz(s for s in (_seviye(o) for o in (m.get("supported_reasoning_levels") or [])) if s)
        adaylar.append((oncelik, sira, mid, m, seviyeler))
    if not adaylar:
        return None
    adaylar.sort(key=lambda t: (t[0], t[1]))
    modeller, tum = [], []
    for _, _, mid, m, seviyeler in adaylar:
        ad = m.get("display_name") if isinstance(m.get("display_name"), str) and m.get("display_name").strip() else mid
        modeller.append(_model(mid, ad, "reasoning", seviyeler))
        tum += seviyeler
    sira = ["low", "medium", "high", "xhigh", "max", "ultra"]
    benzersiz = _siralı_benzersiz(tum)
    efforts = sorted(benzersiz, key=lambda e: (sira.index(e) if e in sira else len(sira), benzersiz.index(e)))
    ilk = adaylar[0][3]
    varsayilan = ilk.get("default_reasoning_level")
    if not (isinstance(varsayilan, str) and EFFORT_RE.match(varsayilan)):
        varsayilan = "medium" if (not efforts or "medium" in efforts) else efforts[0]
    return {"models": modeller, "efforts": efforts or list(FALLBACK_DATA["codex"]["efforts"]),
            "default_model": modeller[0]["id"], "default_effort": varsayilan}


def muse_help_coz(metin: str) -> Tuple[List[str], Optional[str]]:
    """`muse exec --help`: "--reasoning-effort <EFFORT> ... none|minimal|low|...|ultra (default: high; ...)"."""
    t = temizle(metin)
    i = t.find("--reasoning-effort")
    if i < 0:
        return [], None
    parca = t[i:i + 500]
    m = re.search(r"\b([a-z0-9_-]+(?:\|[a-z0-9_-]+)+)", parca)
    d = re.search(r"default:\s*([a-z0-9_-]+)", parca)
    return ([e for e in (m.group(1).split("|") if m else []) if EFFORT_RE.match(e)],
            d.group(1) if d and EFFORT_RE.match(d.group(1)) else None)


def liste_coz(metin: str) -> List[dict]:
    """Özel ajanın model komutu çıktısı (ör. `mimo.exe models`): her satırın İLK boşluklu parçası model kimliği
    regex'ine uyuyorsa model sayılır (`xiaomi/mimo-v2.6-flash — window 1.05M, ...`: kalanı yok sayılır)."""
    modeller: List[dict] = []
    for satir in temizle(metin).splitlines():
        parca = satir.strip().split(None, 1)
        if parca and _kimlik_gibi(parca[0]) and not any(m["id"] == parca[0] for m in modeller):
            modeller.append(_model(parca[0], parca[0], "special"))
    return modeller


# ── Keşif işlevleri (başarısızsa KesifHatasi; herkese açık kesfet_* sarmalayıcıları None döner) ──────

def _kesfet_agy() -> dict:
    yol = _bul("agy", "agy.exe")
    if not yol:
        raise KesifHatasi("agy bulunamadı")
    with ThreadPoolExecutor(max_workers=2) as ex:
        modeller_is = ex.submit(_calistir, [yol, "models"])
        yardim_is = ex.submit(_calistir, [yol, "--help"])
        kod, cikti, hata = modeller_is.result()
        try:
            _, y_out, y_err = yardim_is.result()
            seviyeler = agy_effort_coz(y_out + "\n" + y_err)
        except KesifHatasi:
            seviyeler = []
    modeller = agy_coz(cikti)
    if not modeller:
        raise KesifHatasi("agy models liste vermedi: %s" % (_ilk_satir(hata, cikti) or "kod %s" % kod))
    seviyeler = seviyeler or list(FALLBACK_DATA["agy"]["efforts"])
    return _girdi(modeller, seviyeler, modeller[0]["id"], "high" if "high" in seviyeler else seviyeler[-1])


def _kesfet_claude() -> dict:
    yol = _bul("claude.cmd", "claude")
    if not yol:
        raise KesifHatasi("claude bulunamadı")
    env = {k: v for k, v in os.environ.items() if k not in CLAUDE_TEMIZLE}
    env["PYTHONUTF8"] = "1"
    with ThreadPoolExecutor(max_workers=2) as ex:
        model_is = ex.submit(_calistir, [yol, "-p", "/model"], None, env)
        effort_is = ex.submit(_calistir, [yol, "-p", "/effort"], None, env)
        kod, cikti, hata = model_is.result()
        try:
            seviyeler = claude_effort_coz(effort_is.result()[1])
        except KesifHatasi:
            seviyeler = []
    modeller = claude_modeller_coz(cikti)
    if not modeller:
        raise KesifHatasi("claude /model çıktısında 'Available:' listesi yok: %s" % (_ilk_satir(cikti, hata) or "kod %s" % kod))
    seviyeler = seviyeler or list(CLAUDE_EFFORTS)
    ids = [m["id"] for m in modeller]
    return _girdi(modeller, seviyeler, "default" if "default" in ids else ids[0], "high" if "high" in seviyeler else seviyeler[-1])


def codex_cache_yolu() -> str:
    return os.path.join(os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex"), "models_cache.json")


def _kesfet_codex() -> dict:
    yol = codex_cache_yolu()
    try:
        with open(yol, encoding="utf-8-sig") as f:
            ham = json.load(f)
    except FileNotFoundError:
        raise KesifHatasi("codex model önbelleği yok: %s" % yol)
    except (OSError, ValueError) as e:
        raise KesifHatasi("codex model önbelleği okunamadı (%s): %s" % (yol, e))
    sonuc = codex_coz(ham)
    if not sonuc:
        raise KesifHatasi("codex model önbelleğinde listelenen model yok")
    return _girdi(sonuc["models"], sonuc["efforts"], sonuc["default_model"], sonuc["default_effort"])


def _kesfet_muse() -> dict:
    """Muse'ta model listeleyen komut yok: model yalnız CLI'nin kendi varsayılanı; seviyeler `exec --help`'ten."""
    yol = _bul("muse.cmd", "muse")
    if not yol:
        raise KesifHatasi("muse bulunamadı")
    _, out, err = _calistir([yol, "exec", "--help"])
    seviyeler, varsayilan = muse_help_coz(out + "\n" + err)
    if not seviyeler:
        raise KesifHatasi("muse exec --help'te --reasoning-effort bulunamadı")
    return _girdi([_yedek_model("default")], seviyeler, "default",
                  varsayilan if varsayilan in seviyeler else ("high" if "high" in seviyeler else seviyeler[-1]))


def _kesfet_ozel(spec: dict) -> dict:
    komut = spec.get("model_komutu") or []
    if not komut:
        raise KesifHatasi("model_komutu tanımlı değil")
    yol = _bul(spec["komut"])
    if not yol:
        raise KesifHatasi("%s bulunamadı" % spec["komut"])
    kod, cikti, hata = _calistir([yol, *komut])
    modeller = liste_coz(cikti)
    if not modeller:
        raise KesifHatasi("%s model listesi vermedi: %s" % (spec["anahtar"], _ilk_satir(hata, cikti) or "kod %s" % kod))
    ids = [m["id"] for m in modeller]
    efforts = list(spec.get("efforlar") or [])
    vm = spec.get("varsayilan_model")
    ve = spec.get("varsayilan_effort")
    return _girdi(modeller, efforts, vm if vm in ids else ids[0], ve or (efforts[0] if efforts else "default"))


def _sarmala(ad: str, fn: Callable[..., dict], *arg) -> Optional[dict]:
    try:
        return fn(*arg)
    except KesifHatasi as e:
        uyari("%s keşfi başarısız: %s" % (ad, e))
    except Exception as e:  # beklenmeyen ayrıştırma hatası da önceki iyi veriyi ezmesin
        uyari("%s keşfi beklenmedik hata: %s: %s" % (ad, type(e).__name__, e))
    return None


def kesfet_agy() -> Optional[dict]:
    return _sarmala("agy", _kesfet_agy)


def kesfet_claude() -> Optional[dict]:
    return _sarmala("claude", _kesfet_claude)


def kesfet_codex() -> Optional[dict]:
    return _sarmala("codex", _kesfet_codex)


def kesfet_muse() -> Optional[dict]:
    return _sarmala("muse", _kesfet_muse)


def kesfet_ozel(spec: dict) -> Optional[dict]:
    return _sarmala(spec.get("anahtar", "özel"), _kesfet_ozel, spec)


_KESIFLER = {"claude": kesfet_claude, "agy": kesfet_agy, "codex": kesfet_codex, "muse": kesfet_muse}


def ozel_anahtar(anahtar: str) -> str:
    return "ozel:" + anahtar


def _ozel_ajanlar() -> Dict[str, dict]:
    """Model komutu olan özel ajanlar: {önbellek anahtarı: spec}."""
    try:
        import ozel_ajan
        return {ozel_anahtar(a["anahtar"]): a for a in ozel_ajan.yukle()["ozel"] if a.get("model_komutu")}
    except Exception as e:
        uyari("özel ajanlar okunamadı: %s" % e)
        return {}


# ── Önbellek ───────────────────────────────────────────────────────────────────────────────────

def _girdi_dogrula(g) -> Optional[dict]:
    """Önbellekteki bir sağlayıcı girdisini doğrular/normalleştirir; kullanılamazsa None."""
    if not isinstance(g, dict) or not isinstance(g.get("models"), list):
        return None
    modeller = []
    for m in g["models"]:
        if not isinstance(m, dict) or not isinstance(m.get("id"), str) or not MODEL_RE.match(m["id"]):
            continue
        ef = [e for e in (m.get("efforlar") or []) if isinstance(e, str) and EFFORT_RE.match(e)] \
            if isinstance(m.get("efforlar"), list) else []
        modeller.append(_model(m["id"], m["name"] if isinstance(m.get("name"), str) and m["name"].strip() else m["id"],
                               m["tier"] if isinstance(m.get("tier"), str) else "balanced", ef))
    if not modeller:
        return None
    efforts = [e for e in (g.get("efforts") or []) if isinstance(e, str) and EFFORT_RE.match(e)] \
        if isinstance(g.get("efforts"), list) else []
    ids = [m["id"] for m in modeller]
    dm = g.get("default_model") if g.get("default_model") in ids else ids[0]
    de = g.get("default_effort") if isinstance(g.get("default_effort"), str) and EFFORT_RE.match(g["default_effort"]) else None
    taranma = g.get("taranma") if _zaman(g.get("taranma")) else None
    kaynak = g.get("kaynak") if g.get("kaynak") in ("canli", "onbellek", "yedek", "elle") else "onbellek"
    return {"models": modeller, "efforts": efforts, "default_model": dm, "default_effort": de,
            "taranma": taranma, "kaynak": kaynak}


def cache_oku() -> Tuple[Dict[str, dict], bool]:
    """(sağlayıcı girdileri, dosya geçerli mi). Dosya yok/bozuk → ({}, False). Kullanılamayan girdiler atılır."""
    try:
        with open(cache_yolu(), encoding="utf-8-sig") as f:
            ham = json.load(f)
    except FileNotFoundError:
        return {}, False
    except (OSError, ValueError) as e:
        uyari("%s okunamadı: %s" % (cache_yolu(), e))
        return {}, False
    if not isinstance(ham, dict):
        return {}, False
    veri = {}
    for anahtar, g in ham.items():
        d = _girdi_dogrula(g)
        if d is not None:
            veri[anahtar] = d
    return veri, True


def yedek_girdi(anahtar: str) -> dict:
    g = copy.deepcopy(FALLBACK_DATA[anahtar])
    g.update(taranma=None, kaynak="yedek")
    return g


def birlestir(veri: Dict[str, dict]) -> Dict[str, dict]:
    """Önbellek + yedek: dört yerleşik sağlayıcı HER ZAMAN vardır (önbellekte yoksa/bozuksa küçük yedek liste);
    özel ajan girdileri ("ozel:...") olduğu gibi gelir."""
    cikti = {}
    for k in YERLESIK:
        g = veri.get(k) or yedek_girdi(k)
        g = dict(g)
        if not g.get("efforts"):
            g["efforts"] = list(FALLBACK_DATA[k]["efforts"])
        if not g.get("default_effort"):
            g["default_effort"] = FALLBACK_DATA[k]["default_effort"]
        cikti[k] = g
    for k, g in veri.items():
        if k.startswith("ozel:"):
            cikti[k] = g
    return cikti


def load_cached_models() -> Dict[str, dict]:
    """Önbellekteki model listeleri (eksik sağlayıcılar küçük yedekle tamamlanmış). Ağa/CLI'ya DOKUNMAZ."""
    return birlestir(cache_oku()[0])


def save_cached_models(data: Dict[str, dict]) -> bool:
    """Atomik yazım (geçici dosya + os.replace). Başarısızsa stderr'e yazar, False döner."""
    yol = cache_yolu()
    try:
        klasor = os.path.dirname(os.path.abspath(yol))
        os.makedirs(klasor, exist_ok=True)
        fd, gecici = tempfile.mkstemp(dir=klasor, prefix=".models-", suffix=".yeni")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(gecici, yol)
        except BaseException:
            try:
                os.remove(gecici)
            except OSError:
                pass
            raise
        return True
    except Exception as e:
        uyari("önbellek yazılamadı (%s): %s" % (yol, e))
        return False


def _bayat_girdi(g: Optional[dict], simdi: Optional[datetime] = None) -> bool:
    z = _zaman((g or {}).get("taranma"))
    if z is None:
        return True
    return ((simdi or datetime.now(timezone.utc)) - z).total_seconds() > TTL_SN


def bayat(data: Optional[Dict[str, dict]] = None) -> bool:
    """Herhangi bir sağlayıcı (dört yerleşik ve model komutu olan özel ajanlar) hiç taranmamış ya da TTL_SN'den
    eskiyse True. `data` verilmezse önbellek dosyası okunur."""
    if data is None:
        data = cache_oku()[0]
    simdi = datetime.now(timezone.utc)
    anahtarlar = list(YERLESIK) + list(_ozel_ajanlar())
    return any(_bayat_girdi(data.get(k), simdi) for k in anahtarlar)


def en_eski_taranma(data: Dict[str, dict]) -> Optional[str]:
    zamanlar = [(_zaman(g.get("taranma")), g.get("taranma")) for g in data.values() if _zaman(g.get("taranma"))]
    return min(zamanlar, key=lambda t: t[0])[1] if zamanlar else None


# ── Paralel keşif ve senkronizasyon ────────────────────────────────────────────────────────────

def _paralel(isler: Dict[str, Callable[[], Optional[dict]]]) -> Dict[str, Optional[dict]]:
    """Bütün işleri aynı anda çalıştırır; takılan biri ötekileri geciktirmez (her kaynak kendi alt süreç
    süresiyle sınırlıdır). Süre aşımında o kaynak başarısız sayılır."""
    sonuc: Dict[str, Optional[dict]] = {k: None for k in isler}
    if not isler:
        return sonuc
    ex = ThreadPoolExecutor(max_workers=min(8, len(isler)))
    try:
        gelecek = {ex.submit(fn): k for k, fn in isler.items()}
        bitti, bitmeyen = wait(list(gelecek), timeout=KESIF_SINIRI_SN * 2 + 20)
        for f in bitti:
            sonuc[gelecek[f]] = f.result()
        for f in bitmeyen:
            uyari("%s keşfi süre aşımına uğradı" % gelecek[f])
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return sonuc


def sync_all_models(force: bool = False) -> Dict[str, dict]:
    """Eksik/bayat sağlayıcıları (force=True: hepsini) CLI'lardan paralel yeniden okur ve önbelleğe yazar.
    Başarısız kaynakta önceki iyi veri korunur (kaynak "onbellek"); hiç veri yoksa küçük yedek yazılır.
    Dönüş: load_cached_models() ile aynı biçimde birleşik veri."""
    ham, _ = cache_oku()
    ozel = _ozel_ajanlar()
    kesifler: Dict[str, Callable[[], Optional[dict]]] = dict(_KESIFLER)
    for k, spec in ozel.items():
        kesifler[k] = (lambda s=spec: kesfet_ozel(s))
    gerekenler = [k for k in kesifler if force or _bayat_girdi(ham.get(k))]
    sonuclar = _paralel({k: kesifler[k] for k in gerekenler})
    degisti = bool(gerekenler)
    for k in gerekenler:
        yeni, eski = sonuclar.get(k), ham.get(k)
        if yeni:
            ham[k] = yeni
        elif eski:
            eski["kaynak"] = "onbellek"        # önceki iyi veri korunur (taranma eski kalır: bayat görünür)
        elif k in YERLESIK:
            ham[k] = yedek_girdi(k)            # dosya hiç yoksa sonraki çağrı her seferinde 60 sn denemesin
    for k in [k for k in ham if k.startswith("ozel:") and k not in ozel]:
        del ham[k]                              # silinmiş/model komutu kaldırılmış özel ajan
        degisti = True
    if degisti:
        save_cached_models(ham)
    return birlestir(ham)


if __name__ == "__main__":
    veri = sync_all_models(force="--tara" in sys.argv)
    for anahtar, g in veri.items():
        print("%-14s %-8s %-25s %d model, varsayılan %s" % (anahtar, g.get("kaynak"), g.get("taranma"), len(g["models"]), g["default_model"]))
