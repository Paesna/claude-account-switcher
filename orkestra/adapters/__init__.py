"""
CLI Adapters export.
"""
from typing import Dict, Optional
from .base import BaseCLIAdapter
from .claude_adapter import ClaudeCodeAdapter
from .agy_adapter import AntigravityAdapter
from .codex_adapter import CodexAdapter
from .muse_adapter import MuseCodeAdapter
from .ozel_adapter import OzelAdapter

def create_adapters(
    models_override: Optional[Dict[str, str]] = None,
    efforts_override: Optional[Dict[str, str]] = None
) -> Dict[str, BaseCLIAdapter]:
    models = models_override or {}
    efforts = efforts_override or {}
    adapters: Dict[str, BaseCLIAdapter] = {
        "claude": ClaudeCodeAdapter(
            default_model=models.get("claude", "default"),
            default_effort=efforts.get("claude", "high")
        ),
        "agy": AntigravityAdapter(
            default_model=models.get("agy", "default"),
            default_effort=efforts.get("agy", "high")
        ),
        "codex": CodexAdapter(
            default_model=models.get("codex", "default"),
            default_effort=efforts.get("codex", "medium")
        ),
        "muse": MuseCodeAdapter(
            default_model=models.get("muse", "default"),
            default_effort=efforts.get("muse", "high")
        )
    }
    # Kullanıcının eklediği özel ajanlar (ajanlar.json). Gizlenen yerleşikler de yaratılır: kullanılmazlar,
    # ama ayar değişip geri alınırsa adaptör hazırdır. Fonksiyon içinde içe aktarma: dairesel bağ olmasın.
    import ozel_ajan
    for spec in ozel_ajan.yukle()["ozel"]:
        adapters[spec["anahtar"]] = OzelAdapter(
            spec,
            default_model=models.get(spec["anahtar"]),
            default_effort=efforts.get(spec["anahtar"]),
        )
    return adapters

__all__ = [
    "BaseCLIAdapter",
    "ClaudeCodeAdapter",
    "AntigravityAdapter",
    "CodexAdapter",
    "MuseCodeAdapter",
    "OzelAdapter",
    "create_adapters"
]
