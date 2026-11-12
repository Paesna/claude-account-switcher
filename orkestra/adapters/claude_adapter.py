"""
Adapter for Anthropic Claude Code CLI (`claude.cmd`).

İstem stdin'den gider (`claude -p` argümansız istemi stdin'den okur): `.cmd` kabuğundan geçen
argüman çok satırlı metni bozar ve komut enjeksiyonuna açıktır.
"""
from typing import List, Optional, Tuple
from .base import BaseCLIAdapter

# `claude --help`: --effort <level> (low, medium, high, xhigh, max). Başkasını (ultra, auto) göndermek hata verir.
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")

class ClaudeCodeAdapter(BaseCLIAdapter):
    def __init__(self, default_model: str = "sonnet", default_effort: str = "high"):
        super().__init__(
            key="claude",
            name="Claude Code",
            binary="claude.cmd",
            default_model=default_model,
            default_effort=default_effort
        )

    def _args(self, model: Optional[str], effort: Optional[str]) -> List[str]:
        selected_model = model or self.default_model
        selected_effort = effort or self.default_effort
        cmd = [self.resolved_binary, "-p", "--output-format", "text"]
        if selected_model:
            cmd.extend(["--model", selected_model])
        if selected_effort in CLAUDE_EFFORTS:
            cmd.extend(["--effort", selected_effort])
        return cmd

    def build_command(self, prompt: str, model: Optional[str] = None, effort: Optional[str] = None) -> List[str]:
        # Uyumluluk: istemsiz komut; istem prepare() ile stdin'e gider.
        return self._args(model, effort)

    def prepare(self, prompt: str, model: Optional[str] = None, effort: Optional[str] = None,
                cwd: Optional[str] = None) -> Tuple[List[str], Optional[bytes], List[str]]:
        return self._args(model, effort), prompt.encode("utf-8"), []
