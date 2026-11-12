"""
Protocol & Message definitions for inter-agent communication and token optimization.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
import json

class AgentStatus(Enum):
    IDLE = "IDLE"
    THINKING = "THINKING"
    RUNNING = "RUNNING"
    DELEGATING = "DELEGATING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"

class MessageType(Enum):
    USER_INPUT = "USER_INPUT"
    CHIEF_PLAN = "CHIEF_PLAN"
    TASK_DELEGATION = "TASK_DELEGATION"
    WORKER_RESPONSE = "WORKER_RESPONSE"
    CHIEF_SYNTHESIS = "CHIEF_SYNTHESIS"
    SYSTEM_ALERT = "SYSTEM_ALERT"

@dataclass
class InterAgentMessage:
    id: str
    timestamp: str
    sender_id: str         # e.g. "claude", "agy", "conductor", "user"
    receiver_id: str       # e.g. "agy", "conductor", "all"
    message_type: MessageType
    summary: str           # Short 1-line summary for TUI feed
    content: str           # Full content / payload
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    task_id: Optional[str] = None
    execution_time_sec: float = 0.0

    def to_compact_dict(self) -> Dict[str, Any]:
        """Convert to compact format to minimize token usage when passed to other models."""
        return {
            "from": self.sender_id,
            "to": self.receiver_id,
            "type": self.message_type.value,
            "summary": self.summary,
            "content": self.content.strip()
        }

@dataclass
class SubTask:
    task_id: str
    title: str
    assigned_worker: str   # 'claude', 'agy', 'codex', 'muse'
    instruction: str
    target_files: List[str] = field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    result: str = ""
    tokens_used: int = 0
    duration_sec: float = 0.0

def estimate_tokens(text: str) -> int:
    """Fast, reliable token approximation: ~4 characters per token for code/English, ~2-3 for non-ascii."""
    if not text:
        return 0
    # Average 3.5 chars per token for code/mixed
    return max(1, int(len(text) / 3.5))

def compact_prompt_for_worker(task: SubTask, conductor_name: str) -> str:
    """
    Formats an ultra-compact instruction for a worker CLI.
    Enforces diff-only or summary-only response to save maximum tokens.
    """
    files_clause = f"Target Files: {', '.join(task.target_files)}" if task.target_files else "No specific files."
    prompt = (
        f"[ORCHESTRATOR INSTRUCTION - CHIEF: {conductor_name}]\n"
        f"Task: {task.title}\n"
        f"{files_clause}\n"
        f"Instruction: {task.instruction}\n\n"
        f"TOKEN EFFICIENCY RULES:\n"
        f"1. Be extremely concise. Do NOT echo this prompt.\n"
        f"2. Return ONLY: (a) action taken, (b) code patch/diff or concrete result, (c) 1-sentence verification.\n"
        f"3. Avoid chit-chat or long narrative introductions."
    )
    return prompt
