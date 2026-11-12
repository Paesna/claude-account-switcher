"""
Global configuration for AI Orchestration Engine.
Integrates dynamic model & reasoning effort discovery from native CLIs.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import ozel_ajan
from model_discovery import load_cached_models, sync_all_models

@dataclass
class ModelInfo:
    id: str
    name: str
    tier: str  # "fast", "balanced", "reasoning", "special"
    cost_per_million_input: float = 1.0
    cost_per_million_output: float = 4.0

@dataclass
class ProviderConfig:
    key: str
    name: str
    binary: str
    default_model: str
    default_effort: str
    models: List[ModelInfo]
    efforts: List[str]
    color: str
    icon: str
    description: str

def _custom_provider(spec: dict) -> ProviderConfig:
    """ProviderConfig for a user-defined agent (ajanlar.json). Empty model/effort lists show a single
    "default" entry, which adds no CLI argument (see adapters/ozel_adapter.py)."""
    models = [ModelInfo(m, m, "special") for m in spec["modeller"]] or [ModelInfo("default", "Varsayılan model", "special")]
    efforts = list(spec["efforlar"]) or ["default"]
    return ProviderConfig(
        key=spec["anahtar"],
        name=spec["ad"],
        binary=spec["komut"],
        default_model=spec["varsayilan_model"] or models[0].id,
        default_effort=spec["varsayilan_effort"] or efforts[0],
        models=models,
        efforts=efforts,
        color="bright_yellow",
        icon=spec["ikon"],
        description="Özel ajan: %s" % spec["komut"],
    )


def get_live_providers(include_hidden: bool = False) -> Dict[str, ProviderConfig]:
    """Builds ProviderConfig dynamically using models and efforts fetched from CLIs.

    Built-in agents the user removed from the list (ajanlar.json "gizli") are left out unless
    `include_hidden`; custom agents are appended. No ajanlar.json = the four built-in agents."""
    settings = ozel_ajan.yukle()
    providers = _builtin_providers()
    if not include_hidden:
        for key in settings["gizli"]:
            providers.pop(key, None)
    for spec in settings["ozel"]:
        providers[spec["anahtar"]] = _custom_provider(spec)
    return providers


def _builtin_providers() -> Dict[str, ProviderConfig]:
    data = load_cached_models()
    if not data or not all(k in data for k in ["claude", "agy", "codex", "muse"]):
        data = sync_all_models(force=False)

    return {
        "claude": ProviderConfig(
            key="claude",
            name="Claude Code",
            binary="claude.cmd",
            default_model=data["claude"].get("default_model", "sonnet"),
            default_effort=data["claude"].get("default_effort", "high"),
            models=[ModelInfo(m["id"], m["name"], m.get("tier", "balanced")) for m in data["claude"]["models"]],
            efforts=data["claude"].get("efforts", ["low", "medium", "high", "xhigh", "max"]),
            color="bright_magenta",
            icon="[C]",
            description="Anthropic Claude Code CLI - Derin refaktör ve mimari analiz"
        ),
        "agy": ProviderConfig(
            key="agy",
            name="Google Antigravity (AGY)",
            binary="agy.exe",
            default_model=data["agy"].get("default_model", "gemini-3.8-flash-high"),
            default_effort=data["agy"].get("default_effort", "high"),
            models=[ModelInfo(m["id"], m["name"], m.get("tier", "fast")) for m in data["agy"]["models"]],
            efforts=data["agy"].get("efforts", ["low", "medium", "high"]),
            color="bright_cyan",
            icon="[G]",
            description="Google Antigravity CLI - Ajanik planlama, subagent ve skills"
        ),
        "codex": ProviderConfig(
            key="codex",
            name="OpenAI Codex",
            binary="codex.cmd",
            default_model=data["codex"].get("default_model", "gpt-6-astra"),
            default_effort=data["codex"].get("default_effort", "xhigh"),
            models=[ModelInfo(m["id"], m["name"], m.get("tier", "reasoning")) for m in data["codex"]["models"]],
            efforts=data["codex"].get("efforts", ["low", "medium", "high", "xhigh"]),
            color="bright_green",
            icon="[X]",
            description="OpenAI Codex CLI - Yüksek akıl yürütme ve fonksiyon üretimi"
        ),
        "muse": ProviderConfig(
            key="muse",
            name="Meta Muse Code",
            binary="muse.cmd",
            default_model=data["muse"].get("default_model", "muse-spark"),
            default_effort=data["muse"].get("default_effort", "high"),
            models=[ModelInfo(m["id"], m["name"], m.get("tier", "balanced")) for m in data["muse"]["models"]],
            efforts=data["muse"].get("efforts", ["low", "medium", "high", "xhigh", "max"]),
            color="bright_blue",
            icon="[M]",
            description="Meta Muse Code CLI - Modüler bileşenler ve açık modeller"
        )
    }

AVAILABLE_PROVIDERS = get_live_providers()
# A removed (hidden) agent must not be the default; custom agents are never default workers.
DEFAULT_CONDUCTOR = "claude" if "claude" in AVAILABLE_PROVIDERS else next(iter(AVAILABLE_PROVIDERS), "claude")
DEFAULT_WORKERS = [k for k in ("agy", "codex", "muse") if k in AVAILABLE_PROVIDERS]
