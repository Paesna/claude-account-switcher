"""
Sahte adaptörler: gerçek CLI çağırmadan, kota yakmadan orkestra akışını uçtan uca sınamak için
(`runner.py --calistir spec.json --sahte`). Şef geçerli bir plan JSON'u, işçiler birkaç satır akış
ve sahte sonuç, sentez kısa metin döndürür.
"""
import asyncio
import json
import os
import time
from typing import Callable, Dict, List, Optional, Tuple

from adapters.base import BaseCLIAdapter

# Panelin iptal/uzun çalışma davranışını sınamak için ortamdan yavaşlatılabilir.
ADIM_BEKLEME_SN = float(os.environ.get("ORKESTRA_SAHTE_BEKLEME", "0.3"))


class SahteAdapter(BaseCLIAdapter):
    def __init__(self, key: str, name: str, worker_keys: List[str]):
        super().__init__(key=key, name=name, binary="sahte", default_model="sahte", default_effort="low")
        self.worker_keys = worker_keys

    def build_command(self, prompt: str, model: Optional[str] = None, effort: Optional[str] = None) -> List[str]:
        return ["sahte"]

    async def _yaz(self, on_output: Optional[Callable[[str], None]], satirlar: List[str]) -> str:
        parcalar = []
        for satir in satirlar:
            parcalar.append(satir + "\n")
            if on_output:
                on_output(satir + "\n")
            await asyncio.sleep(ADIM_BEKLEME_SN)
        return "".join(parcalar)

    async def execute(
        self,
        prompt: str,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        cwd: Optional[str] = None,
        on_output: Optional[Callable[[str], None]] = None,
        timeout: Optional[float] = None,
    ) -> Tuple[int, str, float]:
        basla = time.time()
        self.is_running = True
        try:
            if "CHIEF ORCHESTRATOR AI" in prompt and "AVAILABLE WORKER AGENTS" in prompt:
                # Plan istemi: ilk iki işçiye birer alt görev (tek işçi varsa ikisi de ona).
                isciler = self.worker_keys or [self.key]
                plan = {
                    "analysis": "Sahte plan: hedef iki alt göreve bölündü.",
                    "subtasks": [
                        {"worker": isciler[0], "title": "Sahte görev 1",
                         "instruction": "Hedefin birinci yarısını incele.", "target_files": ["README.md"]},
                        {"worker": isciler[1 % len(isciler)], "title": "Sahte görev 2",
                         "instruction": "Hedefin ikinci yarısını incele.", "target_files": []},
                    ],
                }
                metin = await self._yaz(on_output, [json.dumps(plan, ensure_ascii=False)])
            elif "completed execution reports" in prompt:
                metin = await self._yaz(on_output, [
                    "Sahte sentez: iki alt görev tamamlandı.",
                    "Sonraki adım: gerçek çalıştırmayı sahte kipsiz dene.",
                ])
            else:
                metin = await self._yaz(on_output, [
                    "Eylem: sahte inceleme yapıldı (klasör: %s)." % (cwd or "-"),
                    "Sonuç: değişiklik yok.",
                    "Doğrulama: sahte adaptör gerçek bir şey çalıştırmadı.",
                ])
            return 0, metin, time.time() - basla
        finally:
            self.is_running = False

    async def cancel(self):
        self.is_running = False


def create_fake_adapters(provider_keys: List[str], names: Dict[str, str], worker_keys: List[str]) -> Dict[str, SahteAdapter]:
    return {k: SahteAdapter(k, names.get(k, k), worker_keys) for k in provider_keys}
