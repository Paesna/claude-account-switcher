"""
Global configuration for AI Orchestration Engine.
Integrates dynamic model & reasoning effort discovery from native CLIs.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
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

def get_live_providers() -> Dict[str, ProviderConfig]:
    """Builds ProviderConfig dynamically using models and efforts fetched from CLIs."""
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
DEFAULT_CONDUCTOR = "claude"
DEFAULT_WORKERS = ["agy", "codex", "muse"]
