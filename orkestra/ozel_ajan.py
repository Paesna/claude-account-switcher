"""
Orkestra ajan listesi ayarı: yerleşik ajanı listeden çıkarma (gizleme) ve kullanıcının kendi CLI'ını
"özel ajan" olarak ekleme/silme.

Ayarlar kullanıcı verisidir, depoya girmez: %LOCALAPPDATA%\\claude-account-switcher\\orkestra\\ajanlar.json
(`ORKESTRA_AJANLAR` ortam değişkeniyle başka yol verilebilir). Dosya yoksa liste bugünkü 4 yerleşik ajandır.

    {"gizli": ["muse"], "ozel": [ {anahtar, ad, ikon, komut, argumanlar, model_arg, effort_arg, istem,
                                   modeller, efforlar, varsayilan_model, varsayilan_effort}, ... ]}

Özel ajanın istemi argümanla geçmez: `istem: "dosya"` (geçici utf-8 dosya, `{istem_dosyasi}` yer tutucusu)
ya da `istem: "stdin"`. Yer tutucular yalnız `{klasor}`, `{istem_dosyasi}`, `{model}`, `{effort}`; komut
`shell=True` ile çalışmaz (bkz. adapters/ozel_adapter.py).
"""
import json
import os
import re
import shutil
import sys
import tempfile
from typing import Dict, List, Optional

YERLESIK = ("claude", "agy", "codex", "muse")
ANAHTAR_RE = re.compile(r"^[a-z][a-z0-9_-]{1,19}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/\[\]-]{1,80}$")
EFFORT_RE = re.compile(r"^[a-z0-9_-]{1,20}$")
ISTEM_DOSYASI = "{istem_dosyasi}"

# Panel formunun önerdiği MiMo (Xiaomi mimocode) ayarı. Çağrı `mimo run`'ın başsız kipidir; çıktı insan okunur
# metindir (--format varsayılanı). `-f` bir DİZİ seçeneğidir: ondan sonra gelen konumsal mesaj da dosya
# sayılır, bu yüzden mesaj `-f`'den ÖNCE durur; -m ve --variant `-f`'den sonra gelir ve diziyi sonlandırır.
MIMO_ONAYARI = {
    "anahtar": "mimo",
    "ad": "Xiaomi MiMo",
    "ikon": "[Mi]",
    "komut": "mimo.exe",
    "argumanlar": ["run", "--dir", "{klasor}", "Ekteki istemi uygula.", "-f", "{istem_dosyasi}"],
    "model_arg": ["-m", "{model}"],
    "effort_arg": ["--variant", "{effort}"],
    "istem": "dosya",
    "modeller": ["xiaomi/mimo-v2.6-flash", "xiaomi/mimo-v2.6-pro", "xiaomi/mimo-v2.6-pro-ultraspeed", "mimo/mimo-auto"],
    "efforlar": ["high", "max", "minimal"],
    "varsayilan_model": "xiaomi/mimo-v2.6-flash",
    "varsayilan_effort": "high",
}


def uyari(metin: str) -> None:
    print("ozel_ajan: " + metin, file=sys.stderr)


def ayar_yolu() -> str:
    yol = os.environ.get("ORKESTRA_AJANLAR")
    if yol:
        return yol
    kok = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(kok, "claude-account-switcher", "orkestra", "ajanlar.json")


def _komut_bulundu(komut: str) -> bool:
    return shutil.which(komut) is not None or os.path.isfile(komut)


def _temiz_metin(deger, alan: str, en_cok: int, en_az: int = 1) -> str:
    if not isinstance(deger, str):
        raise ValueError("%s metin olmalı." % alan)
    deger = deger.strip()
    if len(deger) < en_az:
        raise ValueError("%s boş olamaz." % alan)
    if len(deger) > en_cok:
        raise ValueError("%s en çok %d karakter olabilir." % (alan, en_cok))
    if any(ord(c) < 32 or ord(c) == 127 for c in deger):
        raise ValueError("%s denetim karakteri (satır sonu vb.) içeremez." % alan)
    return deger


def _arguman_listesi(ham, alan: str) -> List[str]:
    if ham is None:
        return []
    if not isinstance(ham, list):
        raise ValueError("%s bir liste olmalı." % alan)
    if len(ham) > 40:
        raise ValueError("%s en çok 40 öğe olabilir." % alan)
    cikti = []
    for a in ham:
        if not isinstance(a, str):
            raise ValueError("%s öğeleri metin olmalı." % alan)
        if len(a) > 500:
            raise ValueError("%s öğesi en çok 500 karakter olabilir." % alan)
        if any(c in a for c in "\x00\r\n"):
            raise ValueError("%s öğesi NUL ya da satır sonu içeremez." % alan)
        cikti.append(a)
    return cikti


def _kimlik_listesi(ham, alan: str, desen, en_cok: int) -> List[str]:
    if ham is None:
        return []
    if not isinstance(ham, list):
        raise ValueError("%s bir liste olmalı." % alan)
    cikti: List[str] = []
    for d in ham:
        if not isinstance(d, str) or not desen.match(d):
            raise ValueError("Geçersiz %s: %r" % (alan, d))
        if d not in cikti:
            cikti.append(d)
    if len(cikti) > en_cok:
        raise ValueError("%s en çok %d öğe olabilir." % (alan, en_cok))
    return cikti


def dogrula_ajan(ham, mevcut_anahtarlar=(), kurulu_denetle: bool = True) -> dict:
    """Özel ajan tanımını doğrular ve normalleştirir (ValueError, Türkçe mesaj). `mevcut_anahtarlar`:
    çakışmaması gereken özel ajan anahtarları. `kurulu_denetle=False`: komutun bulunmasını aramaz (kayıtlı
    ajan sonradan kaldırılmış olabilir; katalogda "kurulu değil" görünür)."""
    if not isinstance(ham, dict):
        raise ValueError("Ajan tanımı bir nesne olmalı.")
    anahtar = ham.get("anahtar")
    if not isinstance(anahtar, str) or not ANAHTAR_RE.match(anahtar):
        raise ValueError("Anahtar küçük harfle başlamalı ve 2-20 karakter olmalı (a-z, 0-9, - ve _): %r" % (anahtar,))
    if anahtar in YERLESIK:
        raise ValueError("'%s' yerleşik bir ajanın anahtarı; başka bir anahtar seç." % anahtar)
    if anahtar in mevcut_anahtarlar:
        raise ValueError("'%s' anahtarlı bir özel ajan zaten var." % anahtar)

    ad = _temiz_metin(ham.get("ad"), "Ad", 40)
    ikon = ham.get("ikon")
    ikon = _temiz_metin(ikon, "İkon", 8) if isinstance(ikon, str) and ikon.strip() else "[%s]" % anahtar[:2].capitalize()

    komut = _temiz_metin(ham.get("komut"), "Komut", 260)
    if '"' in komut:
        raise ValueError("Komut tırnak içeremez: yalnız program adı ya da dosya yolu yaz.")
    if kurulu_denetle and not _komut_bulundu(komut):
        raise ValueError("Komut bulunamadı: %s (PATH'te olmalı ya da tam yol verilmeli)." % komut)

    argumanlar = _arguman_listesi(ham.get("argumanlar"), "Argümanlar")
    model_arg = _arguman_listesi(ham.get("model_arg"), "Model argümanı")
    effort_arg = _arguman_listesi(ham.get("effort_arg"), "Akıl yürütme argümanı")
    if model_arg and not any("{model}" in a for a in model_arg):
        raise ValueError("Model argümanı {model} yer tutucusunu içermeli.")
    if effort_arg and not any("{effort}" in a for a in effort_arg):
        raise ValueError("Akıl yürütme argümanı {effort} yer tutucusunu içermeli.")

    istem = ham.get("istem", "dosya")
    if istem not in ("dosya", "stdin"):
        raise ValueError("İstem 'dosya' ya da 'stdin' olmalı.")
    hepsi = argumanlar + model_arg + effort_arg
    dosya_var = any(ISTEM_DOSYASI in a for a in hepsi)
    if istem == "dosya" and not dosya_var:
        raise ValueError("İstem dosyayla gidiyor ama argümanlarda %s yok." % ISTEM_DOSYASI)
    if istem == "stdin" and dosya_var:
        raise ValueError("İstem stdin'den gidiyorsa %s kullanılamaz." % ISTEM_DOSYASI)

    modeller = _kimlik_listesi(ham.get("modeller"), "model", MODEL_RE, 30)
    efforlar = _kimlik_listesi(ham.get("efforlar"), "akıl yürütme seviyesi", EFFORT_RE, 30)
    varsayilan_model = ham.get("varsayilan_model") or ""
    varsayilan_effort = ham.get("varsayilan_effort") or ""
    if not isinstance(varsayilan_model, str) or not isinstance(varsayilan_effort, str):
        raise ValueError("Varsayılan model ve seviye metin olmalı.")
    if varsayilan_model and varsayilan_model not in modeller:
        raise ValueError("Varsayılan model (%s) model listesinde yok." % varsayilan_model)
    if varsayilan_effort and varsayilan_effort not in efforlar:
        raise ValueError("Varsayılan seviye (%s) seviye listesinde yok." % varsayilan_effort)

    return {
        "anahtar": anahtar, "ad": ad, "ikon": ikon, "komut": komut,
        "argumanlar": argumanlar, "model_arg": model_arg, "effort_arg": effort_arg, "istem": istem,
        "modeller": modeller, "efforlar": efforlar,
        "varsayilan_model": varsayilan_model, "varsayilan_effort": varsayilan_effort,
    }


def yukle(yol: Optional[str] = None) -> Dict[str, list]:
    """{"gizli": [...], "ozel": [...]}. Dosya yok ya da bozuksa boş ayar; geçersiz özel kayıt uyarıyla atlanır."""
    yol = yol or ayar_yolu()
    bos: Dict[str, list] = {"gizli": [], "ozel": []}
    try:
        with open(yol, encoding="utf-8-sig") as f:
            ham = json.load(f)
    except FileNotFoundError:
        return bos
    except (OSError, ValueError) as e:
        uyari("%s okunamadı, varsayılan liste kullanılıyor: %s" % (yol, e))
        return bos
    if not isinstance(ham, dict):
        uyari("%s bir nesne değil, yok sayıldı." % yol)
        return bos
    gizli = [k for k in (ham.get("gizli") if isinstance(ham.get("gizli"), list) else []) if k in YERLESIK]
    ozel: List[dict] = []
    for kayit in ham.get("ozel") if isinstance(ham.get("ozel"), list) else []:
        try:
            ozel.append(dogrula_ajan(kayit, mevcut_anahtarlar=[o["anahtar"] for o in ozel], kurulu_denetle=False))
        except ValueError as e:
            uyari("geçersiz özel ajan atlandı (%s): %s" % ((kayit or {}).get("anahtar") if isinstance(kayit, dict) else "?", e))
    return {"gizli": list(dict.fromkeys(gizli)), "ozel": ozel}


def kaydet(ayar: Dict[str, list], yol: Optional[str] = None) -> None:
    """Atomik yazım: geçici dosya + os.replace (okuyan yarım dosya görmesin)."""
    yol = yol or ayar_yolu()
    klasor = os.path.dirname(os.path.abspath(yol))
    os.makedirs(klasor, exist_ok=True)
    fd, gecici = tempfile.mkstemp(dir=klasor, prefix="ajanlar-", suffix=".yeni")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"gizli": ayar.get("gizli", []), "ozel": ayar.get("ozel", [])}, f, ensure_ascii=False, indent=1)
        os.replace(gecici, yol)
    except BaseException:
        try:
            os.remove(gecici)
        except OSError:
            pass
        raise


def ekle(ham, yol: Optional[str] = None) -> dict:
    ayar = yukle(yol)
    ajan = dogrula_ajan(ham, mevcut_anahtarlar=[o["anahtar"] for o in ayar["ozel"]])
    ayar["ozel"].append(ajan)
    kaydet(ayar, yol)
    return ajan


def _gorunen_sayisi(ayar: Dict[str, list]) -> int:
    return len([k for k in YERLESIK if k not in ayar["gizli"]]) + len(ayar["ozel"])


def sil(anahtar: str, yol: Optional[str] = None) -> str:
    """Özel ajanı siler ("silindi"), yerleşik ajanı listeden çıkarır ("gizlendi"). En az bir ajan kalmalı."""
    ayar = yukle(yol)
    if _gorunen_sayisi(ayar) <= 1 and (anahtar in YERLESIK and anahtar not in ayar["gizli"]
                                      or any(o["anahtar"] == anahtar for o in ayar["ozel"])):
        raise ValueError("En az bir ajan kalmalı: son ajan çıkarılamaz.")
    if anahtar in YERLESIK:
        if anahtar in ayar["gizli"]:
            raise ValueError("'%s' zaten listeden çıkarılmış." % anahtar)
        ayar["gizli"].append(anahtar)
        islem = "gizlendi"
    elif any(o["anahtar"] == anahtar for o in ayar["ozel"]):
        ayar["ozel"] = [o for o in ayar["ozel"] if o["anahtar"] != anahtar]
        islem = "silindi"
    else:
        raise ValueError("Bilinmeyen ajan: %s" % anahtar)
    kaydet(ayar, yol)
    return islem


def geri_al(anahtar: str, yol: Optional[str] = None) -> str:
    """Listeden çıkarılan yerleşik ajanı geri koyar."""
    ayar = yukle(yol)
    if anahtar not in YERLESIK:
        raise ValueError("Yalnız çıkarılan yerleşik ajanlar geri alınır; silinen özel ajan yeniden eklenmeli: %s" % anahtar)
    if anahtar not in ayar["gizli"]:
        raise ValueError("'%s' zaten listede." % anahtar)
    ayar["gizli"].remove(anahtar)
    kaydet(ayar, yol)
    return "geri_alindi"


# OzelAdapter adapters paketinde durur (base'e bağlı); burada yeniden dışa verilir. Dosyanın sonunda: adapters
# paketi bu modülü yalnız fonksiyon içinde içe aktardığı için dairesel içe aktarma olmaz.
from adapters.ozel_adapter import OzelAdapter  # noqa: E402,F401
