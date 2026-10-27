from __future__ import annotations

from pathlib import Path
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Static
from tscan.ignore import IgnoreFilter
from tscan.models import Finding, ScanSummary
from tscan.scanner import scan_folder


class TScanApp(App):
    """Interactive TUI for tscan using Textual."""

    TITLE = "tscan"
    BINDINGS = [
        ("q", "quit", "끝"),
        ("r", "rescan", "다시 검사"),
        ("i", "ignore", "괜찮아(무시 목록에)"),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }
    #summary_bar {
        padding: 0 1;
        background: $primary-darken-2;
        color: $text;
        height: 1;
        text-style: bold;
    }
    #findings_table {
        height: 1fr;
    }
    #preview_box {
        height: 9;
        padding: 0 1;
        background: $surface;
        color: $text;
    }
    #preview_header {
        color: $secondary;
        text-style: bold;
    }
    #preview_content {
        height: 5;
        padding: 0 1;
    }
    #preview_footer {
        color: $secondary;
    }
    """

    def __init__(
        self,
        target_path: str | Path = ".",
        summary: ScanSummary | None = None,
    ) -> None:
        super().__init__()
        self.target_path = Path(target_path).resolve()
        self.summary = summary
        self.findings: list[Finding] = summary.findings if summary else []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("검사 준비 중...", id="summary_bar")
        yield DataTable(id="findings_table")
        with Vertical(id="preview_box"):
            yield Static("┌ 미리 보기 ────────────────────────────────────────────────────────┐", id="preview_header")
            yield Static("항목을 선택하면 안전하게 마스킹된 앞뒤 2줄 문맥이 표시됩니다.", id="preview_content")
            yield Static("└───────────────────────────────────────────────────────────────────┘", id="preview_footer")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#findings_table", DataTable)
        table.cursor_type = "row"
        table.add_column("종류", width=14)
        table.add_column("파일", width=40)
        table.add_column("줄", width=6)
        table.add_column("값", width=25)

        if self.summary is not None:
            self._render_summary(self.summary)
        else:
            self.action_rescan()

    def action_rescan(self) -> None:
        """Start background scan in a worker thread."""
        self.query_one("#summary_bar", Static).update("검사 중...")
        self.run_worker(self._scan_worker, thread=True)

    def _scan_worker(self) -> None:
        summary = scan_folder(self.target_path)
        self.call_from_thread(self._render_summary, summary)

    def _render_summary(self, summary: ScanSummary) -> None:
        self.summary = summary
        self.findings = summary.findings

        # Update summary bar
        bar_text = (
            f"tscan · 파일 {summary.scanned_files} · "
            f"찾은 것 {len(summary.findings)} · "
            f"건너뜀 {summary.skipped_files}"
        )
        self.query_one("#summary_bar", Static).update(bar_text)

        # Update findings table
        table = self.query_one("#findings_table", DataTable)
        table.clear()

        for idx, f in enumerate(summary.findings):
            table.add_row(f.kind, f.path, str(f.line), f.masked, key=str(idx))

        preview_content = self.query_one("#preview_content", Static)
        if summary.findings:
            table.focus()
            # Select first row by default and show its preview
            preview_content.update(summary.findings[0].preview)
        else:
            preview_content.update("안전합니다. 비밀 또는 개인정보가 발견되지 않았습니다.")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key and event.row_key.value is not None:
            try:
                idx = int(str(event.row_key.value))
                if 0 <= idx < len(self.findings):
                    finding = self.findings[idx]
                    self.query_one("#preview_content", Static).update(finding.preview)
            except (ValueError, IndexError):
                pass

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value is not None:
            try:
                idx = int(str(event.row_key.value))
                if 0 <= idx < len(self.findings):
                    finding = self.findings[idx]
                    self.query_one("#preview_content", Static).update(finding.preview)
            except (ValueError, IndexError):
                pass

    def action_ignore(self) -> None:
        """Add current finding to .tscanignore and trigger rescan."""
        table = self.query_one("#findings_table", DataTable)
        if not self.findings or table.cursor_row is None:
            self.notify("무시할 항목이 선택되지 않았습니다.", severity="warning")
            return

        idx = table.cursor_row
        if 0 <= idx < len(self.findings):
            finding = self.findings[idx]
            ignore_file = (
                self.target_path if self.target_path.is_dir() else self.target_path.parent
            ) / ".tscanignore"
            rule_str = f"{finding.path}:{finding.line}"
            IgnoreFilter.append_rule(ignore_file, rule_str)
            self.notify(f"무시 목록에 등록되었습니다: {rule_str}", severity="information")
            self.action_rescan()
