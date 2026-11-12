"""
Orchestrator Conductor: Coordinates Chief AI planning, worker task delegation,
token tracking, and inter-agent message streaming.
"""
import asyncio
from datetime import datetime
import json
import re
import time
from typing import Callable, Dict, List, Optional
import uuid

from config import AVAILABLE_PROVIDERS, ProviderConfig
from protocol import (
    AgentStatus,
    InterAgentMessage,
    MessageType,
    SubTask,
    compact_prompt_for_worker,
    estimate_tokens
)
from adapters import BaseCLIAdapter, create_adapters

class ConductorOrchestrator:
    def __init__(
        self,
        conductor_key: str = "claude",
        conductor_model: Optional[str] = None,
        conductor_effort: Optional[str] = None,
        worker_keys: Optional[List[str]] = None,
        models_override: Optional[Dict[str, str]] = None,
        efforts_override: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        adapters: Optional[Dict[str, BaseCLIAdapter]] = None
    ):
        self.conductor_key = conductor_key
        self.worker_keys = worker_keys or [k for k in AVAILABLE_PROVIDERS if k != conductor_key]
        self.models_override = models_override or {}
        self.efforts_override = efforts_override or {}
        # Şef için açık model/effort yoksa o sağlayıcının override'ı geçerli.
        self.conductor_model = conductor_model or self.models_override.get(conductor_key)
        self.conductor_effort = conductor_effort or self.efforts_override.get(conductor_key)
        self.cwd = cwd
        # `adapters` yalnız test/sahte kip için: verilmezse gerçek CLI adaptörleri kurulur.
        self.adapters: Dict[str, BaseCLIAdapter] = adapters or create_adapters(self.models_override, self.efforts_override)
        
        # State
        self.messages: List[InterAgentMessage] = []
        self.current_plan: List[SubTask] = []
        self.agent_statuses: Dict[str, AgentStatus] = {k: AgentStatus.IDLE for k in AVAILABLE_PROVIDERS}
        self.is_busy = False
        
        # Aggregate Token & Cost Metrics
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cached_tokens = 0
        self.total_cost_usd = 0.0

        # Event Callbacks for UI
        self.on_message_callback: Optional[Callable[[InterAgentMessage], None]] = None
        self.on_status_change_callback: Optional[Callable[[str, AgentStatus], None]] = None
        self.on_stream_chunk_callback: Optional[Callable[[str, str], None]] = None  # (agent_key, chunk)

    def set_agent_status(self, agent_key: str, status: AgentStatus):
        self.agent_statuses[agent_key] = status
        if self.on_status_change_callback:
            self.on_status_change_callback(agent_key, status)

    def emit_message(self, msg: InterAgentMessage):
        self.messages.append(msg)
        self.total_input_tokens += msg.input_tokens
        self.total_output_tokens += msg.output_tokens
        self.total_cached_tokens += msg.cached_tokens
        self.total_cost_usd += msg.cost_usd
        if self.on_message_callback:
            self.on_message_callback(msg)

    async def execute_objective(self, user_objective: str) -> str:
        """
        Full orchestration cycle:
        1. Chief AI analyzes objective & generates compact subtasks.
        2. Subtasks dispatched to worker CLIs.
        3. Chief AI synthesizes results.

        Hata ya da iptal olsa da `is_busy` kalkar; şefin durumu ERROR olur.
        """
        self.is_busy = True
        try:
            return await self._run_objective(user_objective)
        except BaseException:
            self.set_agent_status(self.conductor_key, AgentStatus.ERROR)
            raise
        finally:
            self.is_busy = False

    async def _run_objective(self, user_objective: str) -> str:
        start_time = time.time()
        conductor_adapter = self.adapters[self.conductor_key]
        conductor_name = conductor_adapter.name
        
        # 1. Log User Message
        user_msg = InterAgentMessage(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender_id="user",
            receiver_id=self.conductor_key,
            message_type=MessageType.USER_INPUT,
            summary=f"Kullanıcı Hedefi: {user_objective[:80]}...",
            content=user_objective,
            input_tokens=estimate_tokens(user_objective)
        )
        self.emit_message(user_msg)
        
        self.set_agent_status(self.conductor_key, AgentStatus.THINKING)

        # 2. Ask Chief AI to Plan
        available_workers_desc = ", ".join(
            [f"'{k}' ({AVAILABLE_PROVIDERS[k].name})" for k in self.worker_keys]
        )
        plan_prompt = (
            f"You are the CHIEF ORCHESTRATOR AI ({conductor_name}).\n"
            f"USER OBJECTIVE: {user_objective}\n\n"
            f"AVAILABLE WORKER AGENTS: {available_workers_desc}\n\n"
            f"YOUR TASK: Decompose this goal into 1 to 3 targeted, minimal subtasks.\n"
            f"TOKEN OPTIMIZATION: Assign each subtask to the most suitable worker. Minimize redundant work.\n"
            f"OUTPUT FORMAT: Return ONLY a valid JSON object (no surrounding text, no markdown backticks if possible):\n"
            f"{{\n"
            f'  "analysis": "Brief 1-sentence assessment of the task",\n'
            f'  "subtasks": [\n'
            f'    {{\n'
            f'      "worker": "<one of {list(self.worker_keys)}>",\n'
            f'      "title": "<short task name>",\n'
            f'      "instruction": "<precise, minimal instruction for the worker CLI>",\n'
            f'      "target_files": ["<filename if any>"]\n'
            f'    }}\n'
            f'  ]\n'
            f"}}"
        )

        def stream_conductor(chunk: str):
            if self.on_stream_chunk_callback:
                self.on_stream_chunk_callback(self.conductor_key, chunk)

        exit_code, raw_plan_output, duration = await conductor_adapter.execute(
            plan_prompt,
            model=self.conductor_model,
            effort=self.conductor_effort,
            cwd=self.cwd,
            on_output=stream_conductor
        )

        plan_in_tokens = estimate_tokens(plan_prompt)
        plan_out_tokens = estimate_tokens(raw_plan_output)

        subtasks = self._parse_subtasks(raw_plan_output)
        self.current_plan = subtasks

        # Log Chief Plan Message
        chief_plan_msg = InterAgentMessage(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender_id=self.conductor_key,
            receiver_id="all",
            message_type=MessageType.CHIEF_PLAN,
            summary=f"Şef Planı: {len(subtasks)} alt görev oluşturuldu",
            content=raw_plan_output,
            input_tokens=plan_in_tokens,
            output_tokens=plan_out_tokens,
            execution_time_sec=duration
        )
        self.emit_message(chief_plan_msg)
        self.set_agent_status(self.conductor_key, AgentStatus.DELEGATING)

        # 3. Dispatch each Subtask to Worker
        worker_results = []
        for idx, task in enumerate(subtasks, 1):
            worker_key = task.assigned_worker
            if worker_key not in self.adapters:
                worker_key = self.worker_keys[0] if self.worker_keys else self.conductor_key

            worker_adapter = self.adapters[worker_key]
            task.status = AgentStatus.RUNNING  # plan görüntüsü işçi başlarken doğru çıksın
            self.set_agent_status(worker_key, AgentStatus.RUNNING)

            # Compact prompt for worker
            worker_prompt = compact_prompt_for_worker(task, conductor_name)
            worker_in_tokens = estimate_tokens(worker_prompt)

            # Delegation Log
            delegation_msg = InterAgentMessage(
                id=str(uuid.uuid4())[:8],
                timestamp=datetime.now().strftime("%H:%M:%S"),
                sender_id=self.conductor_key,
                receiver_id=worker_key,
                message_type=MessageType.TASK_DELEGATION,
                summary=f"[{idx}/{len(subtasks)}] Görev ➔ {worker_adapter.name}: {task.title}",
                content=worker_prompt,
                input_tokens=worker_in_tokens,
                task_id=task.task_id
            )
            self.emit_message(delegation_msg)

            def stream_worker(chunk: str, wkey=worker_key):
                if self.on_stream_chunk_callback:
                    self.on_stream_chunk_callback(wkey, chunk)

            # Execute Worker CLI
            w_code, w_output, w_dur = await worker_adapter.execute(
                worker_prompt,
                model=self.models_override.get(worker_key),
                effort=self.efforts_override.get(worker_key),
                cwd=self.cwd,
                on_output=stream_worker
            )

            worker_out_tokens = estimate_tokens(w_output)
            task.result = w_output
            task.tokens_used = worker_in_tokens + worker_out_tokens
            task.duration_sec = w_dur
            task.status = AgentStatus.FINISHED if w_code == 0 else AgentStatus.ERROR

            # Worker Response Log
            resp_msg = InterAgentMessage(
                id=str(uuid.uuid4())[:8],
                timestamp=datetime.now().strftime("%H:%M:%S"),
                sender_id=worker_key,
                receiver_id=self.conductor_key,
                message_type=MessageType.WORKER_RESPONSE,
                summary=f"Cevap ⬅ {worker_adapter.name}: Tamamlandı ({w_dur:.1f}s)",
                content=w_output,
                input_tokens=worker_in_tokens,
                output_tokens=worker_out_tokens,
                execution_time_sec=w_dur,
                task_id=task.task_id
            )
            self.emit_message(resp_msg)
            self.set_agent_status(worker_key, AgentStatus.IDLE)
            worker_results.append(f"### [Görev {idx}] {task.title} (İşçi: {worker_adapter.name})\n{w_output}")

        # 4. Chief AI Synthesizes Final Response
        self.set_agent_status(self.conductor_key, AgentStatus.THINKING)
        synthesis_prompt = (
            f"You are the CHIEF ORCHESTRATOR ({conductor_name}).\n"
            f"Original Goal: {user_objective}\n\n"
            f"Here are the completed execution reports from your worker agents:\n\n"
            + "\n\n".join(worker_results) +
            f"\n\nNow synthesize a final, clear, comprehensive response for the user. "
            f"Include summary of changes/findings and next steps. Be concise."
        )

        syn_code, syn_output, syn_dur = await conductor_adapter.execute(
            synthesis_prompt,
            model=self.conductor_model,
            effort=self.conductor_effort,
            cwd=self.cwd,
            on_output=stream_conductor
        )

        syn_in_tokens = estimate_tokens(synthesis_prompt)
        syn_out_tokens = estimate_tokens(syn_output)

        final_msg = InterAgentMessage(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now().strftime("%H:%M:%S"),
            sender_id=self.conductor_key,
            receiver_id="user",
            message_type=MessageType.CHIEF_SYNTHESIS,
            summary="Şef Sentezi: Görev tamamlandı!",
            content=syn_output,
            input_tokens=syn_in_tokens,
            output_tokens=syn_out_tokens,
            execution_time_sec=syn_dur
        )
        self.emit_message(final_msg)

        self.set_agent_status(self.conductor_key, AgentStatus.FINISHED)
        return syn_output

    @staticmethod
    def _extract_plan_json(raw_output: str) -> Optional[dict]:
        """First JSON object in the output that has a "subtasks" list. CLI output may carry warnings
        (stderr is merged) or markdown fences with braces around the plan, so a greedy `{...}` regex
        is not enough: try to decode from every `{`."""
        decoder = json.JSONDecoder()
        for m in re.finditer(r"\{", raw_output):
            try:
                obj, _ = decoder.raw_decode(raw_output[m.start():])
            except ValueError:
                continue
            if isinstance(obj, dict) and isinstance(obj.get("subtasks"), list):
                return obj
        return None

    def _parse_subtasks(self, raw_output: str) -> List[SubTask]:
        """Tries to extract structured JSON subtasks, falls back gracefully if plain text."""
        subtasks: List[SubTask] = []
        try:
            data = self._extract_plan_json(raw_output)
            if data:
                tasks_raw = data.get("subtasks", [])
                for idx, t in enumerate(tasks_raw):
                    worker = str(t.get("worker", "")).lower().strip()
                    # Only the workers the user selected are valid (the prompt offered exactly these).
                    if worker not in self.worker_keys:
                        worker = self.worker_keys[idx % len(self.worker_keys)]
                    files = t.get("target_files") or []
                    subtasks.append(
                        SubTask(
                            task_id=f"T{idx+1}",
                            title=str(t.get("title") or f"Subtask {idx+1}"),
                            assigned_worker=worker,
                            instruction=str(t.get("instruction") or ""),
                            target_files=[str(f) for f in files] if isinstance(files, list) else [str(files)]
                        )
                    )
        except Exception:
            subtasks = []

        # Fallback if no subtasks were parsed
        if not subtasks:
            target_worker = self.worker_keys[0] if self.worker_keys else self.conductor_key
            subtasks.append(
                SubTask(
                    task_id="T1",
                    title="Genel Görev Yürütme",
                    assigned_worker=target_worker,
                    instruction=raw_output[:500] if len(raw_output) > 20 else "Kullanıcı hedefini analiz et ve yürüt."
                )
            )

        return subtasks
