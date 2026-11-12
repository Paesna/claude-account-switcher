"""
Terminal User Interface for Multi-Agent AI Orchestration.
Features:
- Prominent Main Task Prompt input box to direct the Chief AI.
- Keyboard-first controls to select Chief, Models, and Effort levels.
- Live inter-agent chatter log, plan display, and multiplexed CLI terminal tabs.
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
    TabbedContent,
    TabPane
)

from config import AVAILABLE_PROVIDERS, DEFAULT_CONDUCTOR, get_live_providers
from model_discovery import sync_all_models
from orchestrator import ConductorOrchestrator
from protocol import AgentStatus, InterAgentMessage, MessageType, SubTask

class OrchestrationApp(App):
    CSS_PATH = "styles.tcss"
    TITLE = "AI CLI ORCHESTRATOR"
    SUB_TITLE = "Çoklu Yapay Zeka Ajan Yönetim Terminali"

    BINDINGS = [
        Binding("p", "focus_prompt", "Görevi Yaz (Prompt)", priority=True),
        Binding("/", "focus_command", "Hızlı Komut /", priority=True),
        Binding("tab", "focus_next_panel", "Sonraki Panel", priority=True),
        Binding("shift+tab", "focus_prev_panel", "Önceki Panel", priority=True),
        Binding("r", "refresh_live_models", "Modelleri Tara", priority=True),
        Binding("f1", "switch_tab('tab-overview')", "Genel Bakış", priority=True),
        Binding("f2", "switch_tab('tab-claude')", "Claude", priority=True),
        Binding("f3", "switch_tab('tab-agy')", "AGY", priority=True),
        Binding("f4", "switch_tab('tab-codex')", "Codex", priority=True),
        Binding("f5", "switch_tab('tab-muse')", "Muse", priority=True),
        Binding("ctrl+q", "quit_app", "Çıkış"),
    ]

    def __init__(
        self,
        conductor_key: str = DEFAULT_CONDUCTOR,
        conductor_model: Optional[str] = None,
        conductor_effort: Optional[str] = None,
        **kwargs
    ):
        app_kwargs = {k: v for k, v in kwargs.items() if k in ["driver_class", "css_path", "watch_css"]}
        super().__init__(**app_kwargs)
        
        self.providers = get_live_providers()
        self.conductor_key = conductor_key
        
        cfg = self.providers.get(self.conductor_key)
        self.conductor_model = conductor_model or (cfg.default_model if cfg else "default")
        self.conductor_effort = conductor_effort or (cfg.default_effort if cfg else "high")
        
        self.orchestrator = ConductorOrchestrator(
            conductor_key=self.conductor_key,
            conductor_model=self.conductor_model,
            conductor_effort=self.conductor_effort
        )
        self.orchestrator.on_message_callback = self._on_interagent_message
        self.orchestrator.on_status_change_callback = self._on_agent_status_change
        self.orchestrator.on_stream_chunk_callback = self._on_agent_stream_chunk

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._render_header(), id="app-header")

        with Horizontal(id="main-workspace"):
            # LEFT SIDEBAR: Chief, Models, Effort
            with Vertical(id="sidebar-panels"):
                # 1. Chief AI Selector
                with Vertical(classes="control-panel", id="panel-chief"):
                    yield Label(" [1] ORKESTRA ŞEFİ ", classes="panel-title")
                    chief_items = []
                    for key, p in self.providers.items():
                        is_sel = "★ " if key == self.conductor_key else "  "
                        lbl = f"{is_sel}{p.icon} {p.name}"
                        item = ListItem(Label(lbl))
                        item._target_type = "chief"
                        item._target_id = key
                        if key == self.conductor_key:
                            item.add_class("selected-item")
                        chief_items.append(item)
                    yield ListView(*chief_items, id="list-chiefs")

                # 2. Live Models Selector (/model)
                with Vertical(classes="control-panel", id="panel-models"):
                    yield Label(" [2] MODELLER (/model) ", classes="panel-title")
                    yield ListView(id="list-models")

                # 3. Reasoning Effort Selector (/effort)
                with Vertical(classes="control-panel", id="panel-efforts"):
                    yield Label(" [3] AKIL YÜRÜTME (/effort) ", classes="panel-title")
                    yield ListView(id="list-efforts")

            # RIGHT WORKSPACE: Tabs for Task, Overview & Raw Terminal Streams
            with Vertical(id="content-tabs"):
                with TabbedContent(id="tabs-content"):
                    with TabPane("🌟 Ana Görev & Plan [F1]", id="tab-overview"):
                        with Vertical(id="overview-split"):
                            # PROMINENT MAIN TASK PROMPT INPUT BOX
                            with Vertical(id="prompt-box-container"):
                                yield Label("🎯 ORKESTRA ŞEFİNE GÖREV VER (ANA PROMPT):", classes="prompt-box-title")
                                with Horizontal(id="prompt-row"):
                                    yield Input(
                                        placeholder="Şefe vermek istediğiniz ana hedefi yazın (Örn: 'Kullanıcı auth sistemini JWT ile kur ve test yaz')...",
                                        id="task-input"
                                    )
                                    yield Button("▶ BAŞLAT", id="btn-submit-task", variant="success")

                            # Active Subtask Plan
                            with Vertical(id="active-plan-box"):
                                yield Label("[bold cyan]📋 AKTİF GÖREV PLANI (ŞEFİN DAĞITTIĞI İŞLER)[/bold cyan]")
                                yield Static("[dim]Şefe yukarıdaki kutudan bir görev verdiğinizde plan burada oluşturulacaktır.[/dim]", id="plan-text")

                            # Inter-Agent Live Chatter
                            with Vertical(id="live-chatter-box"):
                                yield Label("[bold magenta]💬 AJANLAR ARASI CANLI YAZIŞMALAR VE SENTEZ[/bold magenta]")
                                yield RichLog(id="chatter-log", auto_scroll=True, markup=True, highlight=True)

                    with TabPane("🤖 Claude Code [F2]", id="tab-claude"):
                        yield RichLog(id="log-claude", auto_scroll=True, markup=True, highlight=True, classes="terminal-log")

                    with TabPane("⚡ AGY [F3]", id="tab-agy"):
                        yield RichLog(id="log-agy", auto_scroll=True, markup=True, highlight=True, classes="terminal-log")

                    with TabPane("🧠 Codex [F4]", id="tab-codex"):
                        yield RichLog(id="log-codex", auto_scroll=True, markup=True, highlight=True, classes="terminal-log")

                    with TabPane("🌐 Muse Code [F5]", id="tab-muse"):
                        yield RichLog(id="log-muse", auto_scroll=True, markup=True, highlight=True, classes="terminal-log")

        # BOTTOM QUICK COMMAND BAR (SLASH COMMANDS)
        with Horizontal(id="command-bar-container"):
            yield Input(
                placeholder="[Hızlı Komut] /model <ad>, /effort <seviye>, /chief <şef>, /refresh, /clear, /help...",
                id="cmd-input"
            )

        yield Static(self._render_footer_status(), id="footer-status")
        yield Footer()

    def on_mount(self) -> None:
        self._populate_models_list()
        self._populate_efforts_list()
        self._update_all_headers()
        # Default focus directly to the main prompt box!
        self.query_one("#task-input", Input).focus()

    def _render_header(self) -> str:
        cfg = self.providers.get(self.conductor_key)
        c_name = cfg.name if cfg else self.conductor_key
        tot_tokens = self.orchestrator.total_input_tokens + self.orchestrator.total_output_tokens
        
        return (
            f"[bold cyan]⚡ AI ORCHESTRATOR[/bold cyan] │ "
            f"[bold yellow]ŞEF:[/bold yellow] [bold white]{c_name}[/bold white] │ "
            f"[bold green]MODEL:[/bold green] [white]{self.conductor_model}[/white] │ "
            f"[bold magenta]EFFORT:[/bold magenta] [white]{self.conductor_effort}[/white] │ "
            f"[dim]TOPLAM TOKEN:[/dim] [cyan]{tot_tokens:,}[/cyan]"
        )

    def _render_footer_status(self) -> str:
        items = []
        for k, p in self.providers.items():
            st = self.orchestrator.agent_statuses.get(k, AgentStatus.IDLE)
            color = "green" if st == AgentStatus.RUNNING else ("yellow" if st == AgentStatus.THINKING else "dim")
            items.append(f"{p.icon} {p.name}: [{color}]{st.value}[/{color}]")
        return " │ ".join(items)

    def _populate_models_list(self) -> None:
        list_models = self.query_one("#list-models", ListView)
        list_models.clear()
        
        cfg = self.providers.get(self.conductor_key)
        if not cfg:
            return

        for m in cfg.models:
            is_active = (m.id == self.conductor_model)
            prefix = "● " if is_active else "  "
            item = ListItem(Label(f"{prefix}{m.id} [dim]({m.tier})[/dim]"))
            item._target_type = "model"
            item._target_id = m.id
            if is_active:
                item.add_class("selected-item")
            list_models.append(item)

    def _populate_efforts_list(self) -> None:
        list_efforts = self.query_one("#list-efforts", ListView)
        list_efforts.clear()

        cfg = self.providers.get(self.conductor_key)
        if not cfg:
            return

        for eff in cfg.efforts:
            is_active = (eff == self.conductor_effort)
            prefix = "◆ " if is_active else "  "
            item = ListItem(Label(f"{prefix}{eff}"))
            item._target_type = "effort"
            item._target_id = eff
            if is_active:
                item.add_class("selected-item")
            list_efforts.append(item)

    # --- Keyboard Navigation Actions ---

    def action_focus_prompt(self) -> None:
        """Jump focus to the main task prompt input box."""
        self.query_one("#task-input", Input).focus()

    def action_focus_command(self) -> None:
        """Press '/' to jump to bottom quick command bar."""
        self.query_one("#cmd-input", Input).focus()

    def action_focus_next_panel(self) -> None:
        """Cycle focus between panels."""
        focusable = [
            self.query_one("#task-input", Input),
            self.query_one("#list-chiefs", ListView),
            self.query_one("#list-models", ListView),
            self.query_one("#list-efforts", ListView),
            self.query_one("#cmd-input", Input),
        ]
        curr = self.focused
        idx = 0
        if curr in focusable:
            idx = (focusable.index(curr) + 1) % len(focusable)
        focusable[idx].focus()

    def action_focus_prev_panel(self) -> None:
        focusable = [
            self.query_one("#task-input", Input),
            self.query_one("#list-chiefs", ListView),
            self.query_one("#list-models", ListView),
            self.query_one("#list-efforts", ListView),
            self.query_one("#cmd-input", Input),
        ]
        curr = self.focused
        idx = 0
        if curr in focusable:
            idx = (focusable.index(curr) - 1) % len(focusable)
        focusable[idx].focus()

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_quit_app(self) -> None:
        self.exit()

    def action_refresh_live_models(self) -> None:
        self.notify("CLIs üzerinden modeller ve effort seviyeleri taranıyor...", title="Model Senkronizasyonu")
        self.run_worker(self._async_refresh_models(), exclusive=True)

    async def _async_refresh_models(self):
        await asyncio.to_thread(sync_all_models, force=True)
        self.providers = get_live_providers()
        self._populate_models_list()
        self._populate_efforts_list()
        self._update_all_headers()
        self.notify("Canlı modeller başarıyla güncellendi!", title="Senkronizasyon Tamam")

    # --- List Selection Events ---

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        target_type = getattr(event.item, "_target_type", "")
        target_id = getattr(event.item, "_target_id", "")

        if target_type == "chief":
            new_chief = target_id
            if new_chief in self.providers and new_chief != self.conductor_key:
                self.conductor_key = new_chief
                cfg = self.providers[new_chief]
                self.conductor_model = cfg.default_model
                self.conductor_effort = cfg.default_effort
                
                self.orchestrator.conductor_key = new_chief
                self.orchestrator.conductor_model = self.conductor_model
                self.orchestrator.conductor_effort = self.conductor_effort
                self.orchestrator.worker_keys = [k for k in self.providers if k != new_chief]
                
                # Update UI
                self._update_chiefs_list()
                self._populate_models_list()
                self._populate_efforts_list()
                self._update_all_headers()
                self.notify(f"Şef atandı: {cfg.name} ({self.conductor_model})", title="Orkestra Şefi")

        elif target_type == "model":
            new_model = target_id
            self.conductor_model = new_model
            self.orchestrator.conductor_model = new_model
            self._populate_models_list()
            self._update_all_headers()
            self.notify(f"Model seçildi: {new_model}", title="Model")

        elif target_type == "effort":
            new_eff = target_id
            self.conductor_effort = new_eff
            self.orchestrator.conductor_effort = new_eff
            self._populate_efforts_list()
            self._update_all_headers()
            self.notify(f"Akıl yürütme seviyesi: {new_eff}", title="Effort")

    def _update_chiefs_list(self):
        list_chiefs = self.query_one("#list-chiefs", ListView)
        for child in list_chiefs.children:
            if isinstance(child, ListItem):
                cid = getattr(child, "_target_id", "")
                p = self.providers.get(cid)
                if p:
                    is_sel = (cid == self.conductor_key)
                    prefix = "★ " if is_sel else "  "
                    child.query_one(Label).update(f"{prefix}{p.icon} {p.name}")
                    if is_sel:
                        child.add_class("selected-item")
                    else:
                        child.remove_class("selected-item")

    # --- Button & Input Handling ---

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-submit-task":
            task_input = self.query_one("#task-input", Input)
            task_text = task_input.value.strip()
            if task_text:
                task_input.value = ""
                self._run_goal(task_text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd_text = event.value.strip()
        if not cmd_text:
            return

        event.input.value = ""

        if event.input.id == "task-input":
            # Direct prompt to chief
            self._run_goal(cmd_text)
        elif event.input.id == "cmd-input":
            # Command bar input
            if cmd_text.startswith("/"):
                self._handle_slash_command(cmd_text)
            else:
                self._run_goal(cmd_text)

    def _handle_slash_command(self, cmd: str) -> None:
        parts = cmd.split(maxsplit=1)
        action = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        chatter = self.query_one("#chatter-log", RichLog)

        if action == "/model":
            if arg:
                self.conductor_model = arg
                self.orchestrator.conductor_model = arg
                self._populate_models_list()
                self._update_all_headers()
                chatter.write(f"[bold green]✓ Model güncellendi:[/bold green] [cyan]{arg}[/cyan]")
            else:
                cfg = self.providers.get(self.conductor_key)
                m_list = ", ".join([m.id for m in cfg.models]) if cfg else ""
                chatter.write(f"[yellow]Mevcut model:[/yellow] {self.conductor_model}\n[dim]Seçenekler: {m_list}[/dim]")

        elif action == "/effort":
            if arg:
                self.conductor_effort = arg
                self.orchestrator.conductor_effort = arg
                self._populate_efforts_list()
                self._update_all_headers()
                chatter.write(f"[bold green]✓ Akıl yürütme seviyesi (effort):[/bold green] [yellow]{arg}[/yellow]")
            else:
                cfg = self.providers.get(self.conductor_key)
                eff_list = ", ".join(cfg.efforts) if cfg else ""
                chatter.write(f"[yellow]Mevcut effort:[/yellow] {self.conductor_effort}\n[dim]Seçenekler: {eff_list}[/dim]")

        elif action == "/chief":
            if arg in self.providers:
                self.conductor_key = arg
                cfg = self.providers[arg]
                self.conductor_model = cfg.default_model
                self.conductor_effort = cfg.default_effort
                self.orchestrator.conductor_key = arg
                self.orchestrator.conductor_model = self.conductor_model
                self.orchestrator.conductor_effort = self.conductor_effort
                self.orchestrator.worker_keys = [k for k in self.providers if k != arg]
                self._update_chiefs_list()
                self._populate_models_list()
                self._populate_efforts_list()
                self._update_all_headers()
                chatter.write(f"[bold green]✓ Şef değiştirildi:[/bold green] [magenta]{cfg.name}[/magenta]")
            else:
                chatter.write(f"[bold red]Geçersiz şef.[/bold red] Seçenekler: {list(self.providers.keys())}")

        elif action == "/refresh":
            self.action_refresh_live_models()

        elif action == "/clear":
            chatter.clear()
            self.query_one("#plan-text", Static).update("[dim]Loglar temizlendi.[/dim]")

        elif action in ["/quit", "/exit", ":q"]:
            self.exit()

        elif action == "/help":
            chatter.write(
                "[bold yellow]KOMUTLAR:[/bold yellow]\n"
                "• [bold]/model <ad>[/bold]: Modeli değiştir (model kimliği [2] listesindeki gibi, Örn: /model sonnet; default = CLI'nin kendi modeli)\n"
                "• [bold]/effort <seviye>[/bold]: Akıl yürütme seviyesini ayarla (low, medium, high, xhigh, max, ultra)\n"
                "• [bold]/chief <şef>[/bold]: Orkestra şefini değiştir (claude, agy, codex, muse)\n"
                "• [bold]/refresh[/bold]: CLIs modellerini canlı olarak yeniden tara\n"
                "• [bold]/clear[/bold]: Ekranı temizle\n"
                "• [bold]/quit[/bold]: Çıkış yap"
            )

    def _run_goal(self, goal: str):
        if self.orchestrator.is_busy:
            self.notify("Önceki görev henüz tamamlanmadı!", severity="warning")
            return

        chatter = self.query_one("#chatter-log", RichLog)
        chatter.write(f"\n[bold green]🎯 ŞEFE VERİLEN HEDEF:[/bold green] [white]{goal}[/white]\n")
        self._update_all_headers()
        self.run_worker(self._async_execute_goal(goal), exclusive=True)

    async def _async_execute_goal(self, goal: str):
        chatter = self.query_one("#chatter-log", RichLog)
        try:
            res = await self.orchestrator.execute_objective(goal)
            chatter.write(f"\n[bold yellow]🏆 ŞEF SENTEZİ VE NİHAİ SONUÇ:[/bold yellow]\n{res}\n")
        except Exception as e:
            chatter.write(f"\n[bold red]❌ HATA OLUŞTU:[/bold red] {e}\n")
        finally:
            self._update_all_headers()

    # --- Callbacks & UI Updates ---

    def _update_all_headers(self):
        try:
            self.query_one("#app-header", Static).update(self._render_header())
            self.query_one("#footer-status", Static).update(self._render_footer_status())
        except Exception:
            pass

    def _on_interagent_message(self, msg: InterAgentMessage):
        self.call_from_thread(self._handle_msg_ui, msg)

    def _handle_msg_ui(self, msg: InterAgentMessage):
        try:
            chatter_log = self.query_one("#chatter-log", RichLog)
            sender_cfg = self.providers.get(msg.sender_id)
            sender_badge = f"[{sender_cfg.color}]{sender_cfg.name}[/{sender_cfg.color}]" if sender_cfg else f"[bold]{msg.sender_id}[/bold]"
            
            receiver_cfg = self.providers.get(msg.receiver_id)
            receiver_badge = f"[{receiver_cfg.color}]{receiver_cfg.name}[/{receiver_cfg.color}]" if receiver_cfg else f"[bold]{msg.receiver_id}[/bold]"

            tokens_str = f"({msg.input_tokens + msg.output_tokens} tok)" if (msg.input_tokens + msg.output_tokens) > 0 else ""
            dur_str = f"[{msg.execution_time_sec:.1f}s]" if msg.execution_time_sec > 0 else ""

            line = (
                f"[dim]{msg.timestamp}[/dim] {sender_badge} ➜ {receiver_badge} "
                f"[bold white]{msg.summary}[/bold white] [cyan]{tokens_str}[/cyan] [dim]{dur_str}[/dim]"
            )
            chatter_log.write(line)

            if msg.message_type == MessageType.CHIEF_PLAN:
                self._update_plan_ui()

            self._update_all_headers()
        except Exception:
            pass

    def _on_agent_status_change(self, agent_key: str, status: AgentStatus):
        self.call_from_thread(self._update_all_headers)
        self.call_from_thread(self._update_plan_ui)

    def _update_plan_ui(self):
        try:
            plan_text = self.query_one("#plan-text", Static)
            if not self.orchestrator.current_plan:
                plan_text.update("[dim]Henüz bir alt görev planlanmadı.[/dim]")
                return

            lines = []
            for t in self.orchestrator.current_plan:
                worker_cfg = self.providers.get(t.assigned_worker)
                w_name = worker_cfg.name if worker_cfg else t.assigned_worker
                st = t.status.value
                badge = "[green]✓ BİTTİ[/green]" if st == "FINISHED" else ("[yellow]⚡ ÇALIŞIYOR[/yellow]" if st == "RUNNING" else f"[dim]{st}[/dim]")
                lines.append(f"• [bold]{t.title}[/bold] │ İşçi: [cyan]{w_name}[/cyan] │ Durum: {badge}")
            plan_text.update("\n".join(lines))
        except Exception:
            pass

    def _on_agent_stream_chunk(self, agent_key: str, chunk: str):
        self.call_from_thread(self._handle_chunk_ui, agent_key, chunk)

    def _handle_chunk_ui(self, agent_key: str, chunk: str):
        log_id = f"#log-{agent_key}"
        try:
            agent_log = self.query_one(log_id, RichLog)
            agent_log.write(chunk.rstrip("\r\n"))
        except Exception:
            pass
