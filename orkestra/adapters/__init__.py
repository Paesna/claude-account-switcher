"""
CLI Adapters export.
"""
from typing import Dict, Optional
from .base import BaseCLIAdapter
from .claude_adapter import ClaudeCodeAdapter
from .agy_adapter import AntigravityAdapter
from .codex_adapter import CodexAdapter
from .muse_adapter import MuseCodeAdapter

def create_adapters(
    models_override: Optional[Dict[str, str]] = None,
    efforts_override: Optional[Dict[str, str]] = None
) -> Dict[str, BaseCLIAdapter]:
    models = models_override or {}
    efforts = efforts_override or {}
    return {
        "claude": ClaudeCodeAdapter(
            default_model=models.get("claude", "sonnet"),
            default_effort=efforts.get("claude", "high")
        ),
        "agy": AntigravityAdapter(
            default_model=models.get("agy", "gemini-3.8-flash-high"),
            default_effort=efforts.get("agy", "high")
        ),
        "codex": CodexAdapter(
            default_model=models.get("codex", "gpt-6-astra"),
            default_effort=efforts.get("codex", "xhigh")
        ),
        "muse": MuseCodeAdapter(
            default_model=models.get("muse", "muse-spark"),
            default_effort=efforts.get("muse", "high")
        )
    }

__all__ = [
    "BaseCLIAdapter",
    "ClaudeCodeAdapter",
    "AntigravityAdapter",
    "CodexAdapter",
    "MuseCodeAdapter",
    "create_adapters"
]
