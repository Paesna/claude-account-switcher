"""
Adapter for Meta Muse Code CLI (`muse.cmd`).

İstem geçici dosyadan gider (`--prompt-file`): `.cmd` kabuğundan geçen argüman çok satırlı metni bozar
ve komut enjeksiyonuna açıktır. Bayraklar kullanıcının doğruladığı çağrıdan (agents/muse_agent.md):
`--approval-mode never` onay sorusuna takılıp ölmeyi, `--user-input-auto-resolve` soru sormayı,
`--workspace` yanlış kökte çalışmayı önler.
"""
import os
import tempfile
from typing import List, Optional, Tuple
from .base import BaseCLIAdapter

class MuseCodeAdapter(BaseCLIAdapter):
    def __init__(self, default_model: str = "muse-spark", default_effort: str = "high"):
        super().__init__(
            key="muse",
            name="Meta Muse Code",
            binary="muse.cmd",
            default_model=default_model,
            default_effort=default_effort
        )

    def _args(self, prompt_file: str, model: Optional[str], effort: Optional[str], cwd: Optional[str]) -> List[str]:
        selected_model = model or self.default_model
        selected_effort = effort or self.default_effort
        cmd = [
            self.resolved_binary,
            "exec",
            "--prompt-file", prompt_file,
            "--workspace", cwd or os.getcwd(),
            "--approval-mode", "never",
            "--user-input-auto-resolve",
        ]
        if selected_model and selected_model != "default":
            cmd.extend(["--model", selected_model])
        if selected_effort:
            cmd.extend(["--reasoning-effort", selected_effort])
        return cmd

    def build_command(self, prompt: str, model: Optional[str] = None, effort: Optional[str] = None) -> List[str]:
        # Uyumluluk: istem dosyası yazmadan, yer tutucu yolla.
        return self._args("<istem-dosyasi>", model, effort, None)

    def prepare(self, prompt: str, model: Optional[str] = None, effort: Optional[str] = None,
                cwd: Optional[str] = None) -> Tuple[List[str], Optional[bytes], List[str]]:
        fd, path = tempfile.mkstemp(prefix="muse-istem-", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(prompt)
        return self._args(path, model, effort, cwd), None, [path]
