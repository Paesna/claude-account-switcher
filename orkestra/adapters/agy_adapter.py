"""
Adapter for Google Antigravity CLI (`agy.exe`).
"""
from typing import List, Optional
from .base import BaseCLIAdapter

class AntigravityAdapter(BaseCLIAdapter):
    def __init__(self, default_model: str = "gemini-3.8-flash-high", default_effort: str = "high"):
        super().__init__(
            key="agy",
            name="Google Antigravity (AGY)",
            binary="agy.exe",
            default_model=default_model,
            default_effort=default_effort
        )

    def build_command(self, prompt: str, model: Optional[str] = None, effort: Optional[str] = None) -> List[str]:
        selected_model = model or self.default_model
        selected_effort = effort or self.default_effort
        cmd = [
            self.resolved_binary,
            "-p",
            prompt,
            "--output-format",
            "text",
            "--dangerously-skip-permissions"
        ]
        if selected_model:
            cmd.extend(["--model", selected_model])
        if selected_effort and selected_effort in ["low", "medium", "high"]:
            cmd.extend(["--effort", selected_effort])
        return cmd
