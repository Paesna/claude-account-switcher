"""
Kullanıcının tanımladığı özel CLI ajanı (ajanlar.json, bkz. ozel_ajan.py).

İstem ASLA komut satırı argümanı olarak geçmez (`.cmd` kabuğu çok satırlı metni bozar, `"` ve `&` komut
enjeksiyonuna açar): ya geçici dosyaya (`istem: "dosya"`, `{istem_dosyasi}`) ya da stdin'e gider.
Yer tutucular (`{klasor}`, `{istem_dosyasi}`, `{model}`, `{effort}`) tek geçişte doldurulur; `.format`
kullanılmaz (JSON süslü parantezleri bozulmasın) ve doldurulan değer yeniden genişletilmez.
"""
import os
import re
import tempfile
from typing import Dict, List, Optional, Tuple

from .base import BaseCLIAdapter

YER_TUTUCU = re.compile(r"\{(klasor|istem_dosyasi|model|effort)\}")
# Biçimli çıktı veren CLI'lar (ör. mimo run) renk/imleç kaçışları basar: şefe ve sonuca düz metin gider.
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
# Model/effort listesi boş olan ajanda katalogda tek "default" seçeneği görünür; bu değer argüman eklemez.
VARSAYILAN = "default"


def doldur(parca: str, degerler: Dict[str, str]) -> str:
    return YER_TUTUCU.sub(lambda m: degerler[m.group(1)], parca)


class OzelAdapter(BaseCLIAdapter):
    def __init__(self, spec: dict, default_model: Optional[str] = None, default_effort: Optional[str] = None):
        modeller, efforlar = spec.get("modeller") or [], spec.get("efforlar") or []
        model = default_model or spec.get("varsayilan_model") or (modeller[0] if modeller else VARSAYILAN)
        effort = default_effort or spec.get("varsayilan_effort") or (efforlar[0] if efforlar else VARSAYILAN)
        super().__init__(
            key=spec["anahtar"],
            name=spec["ad"],
            binary=spec["komut"],
            default_model=model,
            default_effort=effort,
        )
        self.spec = spec

    def temizle(self, metin: str) -> str:
        return ANSI.sub("", metin)

    def _args(self, prompt_file: str, model: Optional[str], effort: Optional[str], cwd: Optional[str]) -> List[str]:
        m = model or self.default_model
        e = effort or self.default_effort
        degerler = {
            "klasor": cwd or os.getcwd(),
            "istem_dosyasi": prompt_file,
            "model": m or "",
            "effort": e or "",
        }
        cmd = [self.resolved_binary] + [doldur(a, degerler) for a in self.spec.get("argumanlar") or []]
        if m and m != VARSAYILAN and self.spec.get("model_arg"):
            cmd += [doldur(a, degerler) for a in self.spec["model_arg"]]
        if e and e != VARSAYILAN and self.spec.get("effort_arg"):
            cmd += [doldur(a, degerler) for a in self.spec["effort_arg"]]
        return cmd

    def build_command(self, prompt: str, model: Optional[str] = None, effort: Optional[str] = None) -> List[str]:
        # Uyumluluk: istem dosyası yazmadan, yer tutucu yolla.
        return self._args("<istem-dosyasi>", model, effort, None)

    def prepare(self, prompt: str, model: Optional[str] = None, effort: Optional[str] = None,
                cwd: Optional[str] = None) -> Tuple[List[str], Optional[bytes], List[str]]:
        if self.spec.get("istem") == "stdin":
            return self._args("", model, effort, cwd), prompt.encode("utf-8"), []
        fd, path = tempfile.mkstemp(prefix=self.key + "-istem-", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(prompt)
        return self._args(path, model, effort, cwd), None, [path]
