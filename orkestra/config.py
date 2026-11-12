"""
Global configuration for AI Orchestration Engine.
Integrates dynamic model & reasoning effort discovery from native CLIs.

Model/effort lists come from the discovery cache (see model_discovery.py); importing this module never runs a CLI
or touches the network. `runner.py --katalog` / the TUI `r` key refresh the cache.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import ozel_ajan
from model_discovery import cache_oku, load_cached_models, ozel_anahtar, sync_all_models

@dataclass
class ModelInfo:
    id: str
    name: str
    tier: str  # "fast", "balanced", "reasoning", "special"
    cost_per_million_input: float = 1.0
    cost_per_million_output: float = 4.0
    # Model-specific reasoning levels (e.g. codex: gpt-5.6-terra supports "ultra", others do not). None = provider list.
    efforts: Optional[List[str]] = None

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
    # When the model list was last read from the CLI (ISO UTC) and where it came from:
    # "canli" (read live), "onbellek" (refresh failed, kept previous good data), "yedek" (never read), "elle" (typed in by hand).
    taranma: Optional[str] = None
    kaynak: str = "yedek"

def _modeller(liste) -> List[ModelInfo]:
    return [ModelInfo(m["id"], m["name"], m.get("tier", "balanced"), efforts=m.get("efforlar") or None) for m in liste]

def _custom_provider(spec: dict) -> ProviderConfig:
    """ProviderConfig for a user-defined agent (ajanlar.json). Models: read live with the agent's `model_komutu`
    (cache entry "ozel:<key>") plus the ones typed in by hand; empty lists show a single "default" entry, which
    adds no CLI argument (see adapters/ozel_adapter.py)."""
    elle = [ModelInfo(m, m, "special") for m in spec["modeller"]]
    bulunan = cache_oku()[0].get(ozel_anahtar(spec["anahtar"])) if spec.get("model_komutu") else None
    canli = _modeller(bulunan["models"]) if bulunan else []
    ids = {m.id for m in canli}
    models = canli + [m for m in elle if m.id not in ids] or [ModelInfo("default", "Varsayılan model", "special")]
    efforts = list(spec["efforlar"]) or ["default"]
    ids = [m.id for m in models]
    istenen = spec["varsayilan_model"] or (bulunan["default_model"] if bulunan else "")
    return ProviderConfig(
        key=spec["anahtar"],
        name=spec["ad"],
        binary=spec["komut"],
        default_model=istenen if istenen in ids else ids[0],
        default_effort=spec["varsayilan_effort"] or efforts[0],
        models=models,
        efforts=efforts,
        color="bright_yellow",
        icon=spec["ikon"],
        description="Özel ajan: %s" % spec["komut"],
        taranma=bulunan["taranma"] if bulunan else None,
        kaynak=bulunan["kaynak"] if bulunan else "elle",
    )


def get_live_providers(include_hidden: bool = False) -> Dict[str, ProviderConfig]:
    """Builds ProviderConfig using the models and efforts discovered from the CLIs (discovery cache).

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
    data = load_cached_models()   # cache + small fallback for anything never discovered; no CLI call here

    def prov(key, name, binary, color, icon, description) -> ProviderConfig:
        d = data[key]
        return ProviderConfig(
            key=key,
            name=name,
            binary=binary,
            default_model=d["default_model"],
            default_effort=d["default_effort"],
            models=_modeller(d["models"]),
            efforts=list(d["efforts"]),
            color=color,
            icon=icon,
            description=description,
            taranma=d.get("taranma"),
            kaynak=d.get("kaynak", "yedek"),
        )

    return {
        "claude": prov("claude", "Claude Code", "claude.cmd", "bright_magenta", "[C]",
                       "Anthropic Claude Code CLI - Derin refaktör ve mimari analiz"),
        "agy": prov("agy", "Google Antigravity (AGY)", "agy.exe", "bright_cyan", "[G]",
                    "Google Antigravity CLI - Ajanik planlama, subagent ve skills"),
        "codex": prov("codex", "OpenAI Codex", "codex.cmd", "bright_green", "[X]",
                      "OpenAI Codex CLI - Yüksek akıl yürütme ve fonksiyon üretimi"),
        "muse": prov("muse", "Meta Muse Code", "muse.cmd", "bright_blue", "[M]",
                     "Meta Muse Code CLI - Modüler bileşenler ve açık modeller"),
    }

AVAILABLE_PROVIDERS = get_live_providers()
# A removed (hidden) agent must not be the default; custom agents are never default workers.
DEFAULT_CONDUCTOR = "claude" if "claude" in AVAILABLE_PROVIDERS else next(iter(AVAILABLE_PROVIDERS), "claude")
DEFAULT_WORKERS = [k for k in ("agy", "codex", "muse") if k in AVAILABLE_PROVIDERS]
