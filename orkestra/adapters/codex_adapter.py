"""
Adapter for OpenAI Codex CLI (`codex.cmd`).

İstem stdin'den gider (`codex exec ... -`): `.cmd` kabuğundan geçen argüman çok satırlı metni bozar
ve komut enjeksiyonuna açıktır.
"""
from typing import List, Optional, Tuple
from .base import BaseCLIAdapter

class CodexAdapter(BaseCLIAdapter):
    def __init__(self, default_model: str = "default", default_effort: str = "medium"):
        super().__init__(
            key="codex",
            name="OpenAI Codex",
            binary="codex.cmd",
            default_model=default_model,
            default_effort=default_effort
        )

    def _args(self, model: Optional[str], effort: Optional[str]) -> List[str]:
        selected_model = model or self.default_model
        selected_effort = effort or self.default_effort
        cmd = [
            self.resolved_binary,
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
        ]
        # "default" = CLI'nin kendi varsayılan modeli: -m eklenmez.
        if selected_model and selected_model != "default":
            cmd.extend(["-m", selected_model])
        if selected_effort:
            cmd.extend(["-c", f'model_reasoning_effort="{selected_effort}"'])
        cmd.append("-")  # istem stdin'den
        return cmd

    def build_command(self, prompt: str, model: Optional[str] = None, effort: Optional[str] = None) -> List[str]:
        # Uyumluluk: istemsiz komut; istem prepare() ile stdin'e gider.
        return self._args(model, effort)

    def prepare(self, prompt: str, model: Optional[str] = None, effort: Optional[str] = None,
                cwd: Optional[str] = None) -> Tuple[List[str], Optional[bytes], List[str]]:
        return self._args(model, effort), prompt.encode("utf-8"), []
