"""
Başsız orkestra çalıştırıcısı: Claude hesapları paneli (arayuz.pyw) bunu alt süreç olarak başlatır.

Her olay stdout'a tek satır JSON olarak yazılır (`{"t": "...", ...}`, flush'lı); stdout'a başka bir şey
basılmaz, hata ve traceback stderr'e gider.

  runner.py --katalog [--tara]            Sağlayıcı/model/effort kataloğu (tek satır `katalog`; gizlenen
                                          yerleşik ajanlar `gizli`, özel ajanlar `ozel: true`).
  runner.py --calistir spec.json [--sahte]  Bir hedefi çalıştırır. --sahte: gerçek CLI çağırmaz.
  runner.py --ajan-ekle spec.json         Özel ajan ekler (ozel_ajan.py biçimi); tek satır `tamam` ya da `hata`.
  runner.py --ajan-sil ANAHTAR            Özel ajanı siler / yerleşik ajanı listeden çıkarır (gizler).
  runner.py --ajan-geri ANAHTAR           Listeden çıkarılan yerleşik ajanı geri alır.
  Ajan ayarı: %LOCALAPPDATA%/claude-account-switcher/orkestra/ajanlar.json (ORKESTRA_AJANLAR ile değişir).

spec.json: {"hedef", "sef", "model", "effort", "isciler": [...], "modeller": {anahtar: model},
            "eforlar": {anahtar: effort}, "klasor"}

Olaylar (--calistir): basladi → ajan / plan / mesaj / akim ... → bitti | hata
"""
import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import traceback

KLASOR = os.path.dirname(os.path.abspath(__file__))
if KLASOR not in sys.path:
    sys.path.insert(0, KLASOR)

# Olaylar gerçek stdout'a gider; yanlışlıkla basılan her şey (kütüphane, print) stderr'e.
_CIKTI = sys.stdout
try:
    _CIKTI.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
sys.stdout = sys.stderr

# base.py'nin akışa bastığı Rich işaretleri (TUI içindi); web'de düz metin.
RICH = re.compile(r"\[/?(?:bold red|dim grey|bold|dim)\]")
# Model/effort komut satırına `.cmd` kabuğundan geçer: yalnız zararsız karakterler.
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/\[\]-]{1,80}$")
EFFORT_RE = re.compile(r"^[a-z0-9_-]{1,20}$")


def yaz(t: str, **alanlar) -> None:
    _CIKTI.write(json.dumps({"t": t, **alanlar}, ensure_ascii=False) + "\n")
    _CIKTI.flush()


def kurulu_mu(binary: str) -> bool:
    """PATH'te çözülebilir program adı ya da mevcut dosyanın tam yolu (özel ajanlarda yol da verilebilir)."""
    return shutil.which(binary) is not None or os.path.isfile(binary)


def katalog(tara: bool) -> None:
    import ozel_ajan
    from config import get_live_providers
    from model_discovery import sync_all_models

    if tara:
        sync_all_models(force=True)
    tumu = get_live_providers(include_hidden=True)
    saglayicilar = get_live_providers()
    ozel = {s["anahtar"] for s in ozel_ajan.yukle()["ozel"]}
    gorunen = list(saglayicilar)
    yaz(
        "katalog",
        saglayicilar=[
            {
                "anahtar": p.key,
                "ad": p.name,
                "ikon": p.icon,
                "aciklama": p.description,
                "kurulu": kurulu_mu(p.binary),
                "ozel": p.key in ozel,
                "modeller": [{"id": m.id, "ad": m.name, "kademe": m.tier} for m in p.models],
                "efforlar": list(p.efforts),
                "varsayilan_model": p.default_model,
                "varsayilan_effort": p.default_effort,
            }
            for p in saglayicilar.values()
        ],
        # Listeden çıkarılan yerleşik ajanlar: panel "geri ekle" için gösterir.
        gizli=[{"anahtar": k, "ad": p.name} for k, p in tumu.items() if k not in saglayicilar],
        varsayilan_sef="claude" if "claude" in saglayicilar else (gorunen[0] if gorunen else ""),
        varsayilan_isciler=[k for k in ("agy", "codex", "muse") if k in saglayicilar],
    )


def ajan_islemi(kip: str, arguman: str) -> None:
    """--ajan-ekle <spec.json> | --ajan-sil <anahtar> | --ajan-geri <anahtar>: ajanlar.json'u değiştirir."""
    import ozel_ajan

    if kip == "ekle":
        with open(arguman, encoding="utf-8-sig") as f:
            ham = json.load(f)
        ajan = ozel_ajan.ekle(ham)
        yaz("tamam", anahtar=ajan["anahtar"], islem="eklendi", mesaj="%s listeye eklendi." % ajan["ad"])
    elif kip == "sil":
        islem = ozel_ajan.sil(arguman)
        yaz("tamam", anahtar=arguman, islem=islem,
            mesaj="%s listeden çıkarıldı (geri alınabilir)." % arguman if islem == "gizlendi"
            else "%s silindi." % arguman)
    else:
        islem = ozel_ajan.geri_al(arguman)
        yaz("tamam", anahtar=arguman, islem=islem, mesaj="%s listeye geri alındı." % arguman)


def spec_oku(yol: str) -> dict:
    with open(yol, encoding="utf-8-sig") as f:
        spec = json.load(f)
    if not isinstance(spec, dict):
        raise ValueError("spec bir nesne olmalı.")
    return spec


def dogrula(spec: dict, saglayicilar: dict) -> dict:
    hedef = str(spec.get("hedef") or "").strip()
    if not hedef:
        raise ValueError("Hedef boş.")
    klasor = str(spec.get("klasor") or "").strip()
    if not klasor or not os.path.isdir(klasor):
        raise ValueError("Çalışma klasörü yok: %s" % (klasor or "(boş)"))
    klasor = os.path.abspath(klasor)

    # Şef belirtilmediyse varsayılan: claude, listeden çıkarılmışsa ilk görünen ajan.
    sef = str(spec.get("sef") or ("claude" if "claude" in saglayicilar else next(iter(saglayicilar), "claude")))
    if sef not in saglayicilar:
        raise ValueError("Bilinmeyen şef: %s (seçenekler: %s)" % (sef, ", ".join(saglayicilar)))
    isciler = spec.get("isciler") or []
    if not isinstance(isciler, list) or any(not isinstance(k, str) for k in isciler):
        raise ValueError("isciler bir anahtar listesi olmalı.")
    kotu = [k for k in isciler if k not in saglayicilar]
    if kotu:
        raise ValueError("Bilinmeyen işçi: %s" % ", ".join(kotu))
    isciler = list(dict.fromkeys(isciler))

    modeller_ham = spec.get("modeller") or {}
    eforlar_ham = spec.get("eforlar") or {}
    if not isinstance(modeller_ham, dict) or not isinstance(eforlar_ham, dict):
        raise ValueError("modeller ve eforlar nesne olmalı.")
    if spec.get("model"):
        modeller_ham = {**modeller_ham, sef: spec["model"]}
    if spec.get("effort"):
        eforlar_ham = {**eforlar_ham, sef: spec["effort"]}

    # Her sağlayıcı için açık değer ya da katalog varsayılanı: adaptörler hep belirli bir model alsın.
    modeller, eforlar = {}, {}
    for k, p in saglayicilar.items():
        m = str(modeller_ham.get(k) or p.default_model)
        e = str(eforlar_ham.get(k) or p.default_effort)
        if not MODEL_RE.match(m):
            raise ValueError("Geçersiz model (%s): %r" % (k, m))
        if not EFFORT_RE.match(e):
            raise ValueError("Geçersiz effort (%s): %r" % (k, e))
        modeller[k], eforlar[k] = m, e

    return {
        "hedef": hedef,
        "klasor": klasor,
        "sef": sef,
        # İşçi seçilmediyse şef işi kendisi yapar (conductor boş listeyi "hepsi" sayardı).
        "isciler": isciler or [sef],
        "modeller": modeller,
        "eforlar": eforlar,
    }


def plan_gorunumu(orkestra) -> list:
    return [
        {
            "id": t.task_id,
            "baslik": t.title,
            "isci": t.assigned_worker,
            "talimat": t.instruction,
            "dosyalar": list(t.target_files or []),
            "durum": t.status.name,
            "jeton": t.tokens_used,
            "sure": round(t.duration_sec, 1),
        }
        for t in orkestra.current_plan
    ]


async def calistir(spec_yolu: str, sahte: bool) -> int:
    from config import AVAILABLE_PROVIDERS
    from orchestrator import ConductorOrchestrator

    try:
        spec = dogrula(spec_oku(spec_yolu), AVAILABLE_PROVIDERS)
    except Exception as e:
        yaz("hata", mesaj=str(e))
        return 1

    adaptorler = None
    if sahte:
        from sahte import create_fake_adapters
        adaptorler = create_fake_adapters(
            list(AVAILABLE_PROVIDERS),
            {k: p.name for k, p in AVAILABLE_PROVIDERS.items()},
            spec["isciler"],
        )

    orkestra = ConductorOrchestrator(
        conductor_key=spec["sef"],
        conductor_model=spec["modeller"][spec["sef"]],
        conductor_effort=spec["eforlar"][spec["sef"]],
        worker_keys=spec["isciler"],
        models_override=spec["modeller"],
        efforts_override=spec["eforlar"],
        cwd=spec["klasor"],
        adapters=adaptorler,
    )

    son_plan = [None]

    def plan_yolla():
        gorunum = plan_gorunumu(orkestra)
        anahtar = json.dumps(gorunum, ensure_ascii=False, sort_keys=True)
        if gorunum and anahtar != son_plan[0]:
            son_plan[0] = anahtar
            yaz("plan", gorevler=gorunum)

    def mesaj(m):
        yaz(
            "mesaj",
            id=m.id,
            zaman=m.timestamp,
            gonderen=m.sender_id,
            alici=m.receiver_id,
            tur=m.message_type.value,
            ozet=m.summary,
            icerik=m.content,
            girdi=m.input_tokens,
            cikti=m.output_tokens,
            sure=round(m.execution_time_sec, 1),
            gorev=m.task_id,
        )
        plan_yolla()

    def durum(ajan, d):
        yaz("ajan", ajan=ajan, durum=d.value)
        plan_yolla()

    def akim(ajan, parca):
        metin = RICH.sub("", parca)
        if metin:
            yaz("akim", ajan=ajan, metin=metin)

    orkestra.on_message_callback = mesaj
    orkestra.on_status_change_callback = durum
    orkestra.on_stream_chunk_callback = akim

    yaz("basladi", sef=spec["sef"], model=spec["modeller"][spec["sef"]], effort=spec["eforlar"][spec["sef"]],
        isciler=spec["isciler"], klasor=spec["klasor"])
    try:
        sonuc = await orkestra.execute_objective(spec["hedef"])
    except Exception as e:
        traceback.print_exc()
        yaz("hata", mesaj="%s: %s" % (type(e).__name__, e))
        return 1
    yaz(
        "bitti",
        sonuc=sonuc,
        jeton={
            "girdi": orkestra.total_input_tokens,
            "cikti": orkestra.total_output_tokens,
            "onbellek": orkestra.total_cached_tokens,
        },
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Başsız orkestra çalıştırıcısı (panel için)")
    ap.add_argument("--katalog", action="store_true", help="Sağlayıcı/model kataloğunu yaz")
    ap.add_argument("--tara", action="store_true", help="--katalog ile: CLI'lardan modelleri yeniden tara")
    ap.add_argument("--calistir", metavar="SPEC", help="spec.json yolu")
    ap.add_argument("--sahte", action="store_true", help="--calistir ile: gerçek CLI çağırma")
    ap.add_argument("--ajan-ekle", metavar="SPEC", help="özel ajan ekle (tek ajan nesnesi içeren spec.json)")
    ap.add_argument("--ajan-sil", metavar="ANAHTAR", help="özel ajanı sil / yerleşik ajanı listeden çıkar")
    ap.add_argument("--ajan-geri", metavar="ANAHTAR", help="listeden çıkarılan yerleşik ajanı geri al")
    args = ap.parse_args()
    try:
        if args.katalog:
            katalog(args.tara)
            return 0
        if args.calistir:
            return asyncio.run(calistir(args.calistir, args.sahte))
        for kip, deger in (("ekle", args.ajan_ekle), ("sil", args.ajan_sil), ("geri", args.ajan_geri)):
            if deger:
                try:
                    ajan_islemi(kip, deger)
                except (ValueError, OSError) as e:  # doğrulama/okuma hatası: kullanıcıya düz mesaj, traceback yok
                    yaz("hata", mesaj=str(e))
                    return 1
                return 0
        ap.error("--katalog, --calistir ya da --ajan-ekle/--ajan-sil/--ajan-geri gerekli")
    except Exception as e:
        traceback.print_exc()
        yaz("hata", mesaj="%s: %s" % (type(e).__name__, e))
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
