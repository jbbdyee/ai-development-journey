"""Textual view of one sequential crew run."""

from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Input, Static, TabbedContent, TabPane

from tcrew.core import Config, LLM, Role, RoleResult, RunResult, execute
from tcrew.records import redact, save_record


STATUS = {"waiting": "대기", "running": "실행 중", "completed": "완료", "failed": "실패"}


class CrewApp(App):
    CSS = """
    #summary { height: 3; padding: 0 1; }
    #question { dock: bottom; }
    TabbedContent { height: 1fr; }
    .role-body { padding: 1 2; overflow-y: auto; }
    """
    BINDINGS = [("q", "quit", "종료")]

    def __init__(self, question: str, config: Config, llm: LLM, runs_dir: Path):
        super().__init__()
        self.initial_question = question
        self.config = config
        self.llm = llm
        self.runs_dir = runs_dir
        self.states = {role.name: "waiting" for role in config.roles}
        self.history: dict[str, list[str]] = {role.name: [] for role in config.roles}
        self.result: RunResult | None = None
        self.record_path: Path | None = None
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Static("전체 상태: 대기 / 재작성 0회", id="summary")
        with TabbedContent():
            for index, role in enumerate(self.config.roles):
                with TabPane(role.name, id=f"role-{index}"):
                    yield Static("대기", id=f"body-{index}", classes="role-body")
        yield Input(placeholder="질문을 입력하고 Enter를 누르세요", id="question")
        yield Footer()

    def on_mount(self) -> None:
        if self.initial_question:
            self._start(self.initial_question)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip() and not self.busy:
            self._start(event.value)

    def _start(self, question: str) -> None:
        self.busy = True
        self.result = None
        self.record_path = None
        for index, role in enumerate(self.config.roles):
            self.states[role.name] = "waiting"
            self.history[role.name] = []
            self.query_one(f"#role-{index}", TabPane).title = f"{role.name} · 대기"
            self.query_one(f"#body-{index}", Static).update(Text("대기"))
        self.query_one("#summary", Static).update(Text("전체 상태: 실행 중 / 재작성 0회"))
        self.run_worker(lambda: self._run_question(question), thread=True, exclusive=True)

    def _run_question(self, question: str) -> None:
        result = execute(question, self.config, self.llm, on_event=self._event_from_worker)
        try:
            path = save_record(result, self.runs_dir)
        except OSError:
            path = None
        self.call_from_thread(self._finish, result, path)

    def _event_from_worker(self, role: Role, attempt: int, state: str, item: RoleResult | None) -> None:
        self.call_from_thread(self._apply_event, role.name, attempt, state, item)

    def _apply_event(self, name: str, attempt: int, state: str, item: RoleResult | None) -> None:
        index = next(i for i, role in enumerate(self.config.roles) if role.name == name)
        self.states[name] = state
        label = STATUS[state]
        seconds = f" · {item.duration_seconds:.2f}s" if item else ""
        self.query_one(f"#role-{index}", TabPane).title = f"{name} · {label}{seconds}"
        if item:
            content = f"{name} #{attempt} · {label} · {item.duration_seconds:.2f}s"
            if item.decision:
                content += f" · 판정 {item.decision}"
            if item.reviewer_decision and item.reviewer_decision != item.decision:
                content += f" (Reviewer 응답 {item.reviewer_decision}, 플레이스홀더 차단)"
            if item.validation_feedback:
                content += "\n" + item.validation_feedback
            content += "\n" + redact(item.output)
            if self.history[name] and self.history[name][-1].startswith(f"{name} #{attempt} ·"):
                self.history[name][-1] = content
            elif not self.history[name] or self.history[name][-1] != content:
                self.history[name].append(content)
        body = "\n\n".join(self.history[name]) if self.history[name] else label
        self.query_one(f"#body-{index}", Static).update(Text(body))

    def _finish(self, result: RunResult, path: Path | None) -> None:
        self.result = result
        self.record_path = path
        self.busy = False
        status = "성공" if result.status == "passed" else "실패"
        reason = f" · {result.reason}" if result.reason else ""
        record = "" if path else " · 기록 저장 실패"
        self.query_one("#summary", Static).update(
            Text(f"전체 상태: {status} / 재작성 {result.revisions}회{reason}{record}")
        )
