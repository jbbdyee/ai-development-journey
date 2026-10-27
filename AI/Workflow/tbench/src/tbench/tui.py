"""Live Textual view and local request/result browsers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from .engine import Sample, compare, run
from .storage import history


def sparkline(values: list[float]) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    if not values:
        return ""
    top = max(values)
    return "".join(blocks[min(7, round(value / top * 7))] if top else blocks[0] for value in values)


def seconds(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}s"


class RequestScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, directory: Path):
        super().__init__()
        self.directory = directory

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static(f"Select a JSON request body from {self.directory} (Enter to measure)")
            yield Static("", id="request_status")
            yield DataTable(id="request_files")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#request_files", DataTable)
        table.cursor_type = "row"
        table.add_columns("File", "Bytes")
        try:
            paths = sorted(self.directory.glob("*.json"))
        except OSError as exc:
            self.query_one("#request_status", Static).update(f"Cannot list requests: {exc}")
            return
        for path in paths:
            try:
                table.add_row(path.name, str(path.stat().st_size), key=str(path))
            except OSError:
                continue
        if not table.row_count:
            self.query_one("#request_status", Static).update("No JSON requests found. Esc returns to the run screen.")
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        path = Path(str(event.row_key.value))
        try:
            body = path.read_bytes()
            json.loads(body)
        except (OSError, ValueError) as exc:
            self.query_one("#request_status", Static).update(f"Cannot use {path.name}: {exc}")
            return
        app: BenchmarkApp = self.app  # type: ignore[assignment]
        app.body = body
        app.headers.setdefault("Content-Type", "application/json")
        app.selected_request = path
        app.pop_screen()
        app.start_measurement()


class HistoryScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static("Saved runs, newest first. Enter a run to choose it as the comparison baseline.")
            yield Static("", id="history_status")
            yield DataTable(id="history_rows")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#history_rows", DataTable)
        table.cursor_type = "row"
        table.add_column("Date", width=16)
        table.add_column("URL", width=23)
        table.add_column("N", width=2)
        table.add_column("p50", width=6)
        table.add_column("p95", width=6)
        table.add_column("Failures", width=8)
        try:
            rows = history(include_paths=True)
        except OSError as exc:
            self.query_one("#history_status", Static).update(f"Cannot list runs: {exc}")
            return
        self._urls = {str(row["path"]): row["url"] for row in rows}
        for row in rows:
            short_url = row["url"] if len(row["url"]) <= 23 else row["url"][:22] + "…"
            table.add_row(row["started_at"][:16].replace("T", " "), short_url, str(row["count"]),
                          seconds(row["p50"]), seconds(row["p95"]), str(row["failures"]),
                          key=str(row["path"]))
        if not rows:
            self.query_one("#history_status", Static).update("No saved runs")
        else:
            self.query_one("#history_status", Static).update(f"URL: {rows[0]['url']}")
        table.focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        url = self._urls.get(str(event.row_key.value))
        if url:
            self.query_one("#history_status", Static).update(f"URL: {url}")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.app.push_screen(CompareScreen(Path(str(event.row_key.value))))


class CompareScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, before: Path | None = None):
        super().__init__()
        self.before = before

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static("Select baseline, then comparison run (Enter).")
            yield Static("", id="compare_status")
            yield DataTable(id="compare_files")
            yield Static("", id="compare_warning")
            yield DataTable(id="compare_metrics")
        yield Footer()

    def on_mount(self) -> None:
        files = self.query_one("#compare_files", DataTable)
        files.cursor_type = "row"
        files.add_columns("Date", "URL", "N", "File")
        metrics = self.query_one("#compare_metrics", DataTable)
        metrics.add_columns("Metric", "Before", "After", "Change")
        try:
            rows = history(include_paths=True)
        except OSError as exc:
            self.query_one("#compare_status", Static).update(f"Cannot list runs: {exc}")
            return
        for row in rows:
            files.add_row(row["started_at"], row["url"], str(row["count"]),
                          row["path"].name, key=str(row["path"]))
        if not rows:
            self.query_one("#compare_status", Static).update("No saved runs")
        elif self.before:
            self.query_one("#compare_status", Static).update(f"Baseline: {self.before.name}. Select comparison run.")
        files.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "compare_files":
            return
        path = Path(str(event.row_key.value))
        status = self.query_one("#compare_status", Static)
        if self.before is None:
            self.before = path
            status.update(f"Baseline: {path.name}. Select comparison run.")
            return
        try:
            before = json.loads(self.before.read_text(encoding="utf-8"))
            after = json.loads(path.read_text(encoding="utf-8"))
            report = compare(before, after)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            status.update(f"Cannot compare results: {exc}")
            return
        status.update(f"Before: {self.before.name}  After: {path.name}. Select a run for a new baseline.")
        self.before = None
        warning = self.query_one("#compare_warning", Static)
        warning.update("WARNING: different " + ", ".join(report["warnings"]) if report["warnings"] else "Same URL, body hash, and N")
        metrics = self.query_one("#compare_metrics", DataTable)
        metrics.clear()
        for key, values in report["metrics"].items():
            fmt = str if key == "failures" else seconds
            change = values["change_percent"]
            metrics.add_row(key, fmt(values["before"]), fmt(values["after"]),
                            "—" if change is None else f"{change:+.1f}%")


class BenchmarkApp(App):
    BINDINGS = [("q", "quit", "Quit"), ("h", "show_history", "History"),
                ("c", "show_compare", "Compare")]
    CSS = """
    Vertical { padding: 1 2; }
    #chart { height: 3; }
    #summary { height: 3; }
    #timings { height: 2; }
    #request_status, #history_status, #compare_status, #compare_warning { height: 2; }
    #compare_files { height: 1fr; }
    #compare_metrics { height: 7; }
    DataTable { height: 1fr; }
    """

    def __init__(self, url: str, body: bytes | None, headers: dict[str, str], count: int, timeout: float, warmup: int, concurrency: int = 1, on_sample: Callable[[Sample], None] | None = None, requests_dir: Path = Path("requests"), pick_request: bool = False):
        super().__init__()
        self.url, self.body, self.headers = url, body, headers
        self.count, self.timeout, self.warmup, self.concurrency = count, timeout, warmup, concurrency
        self.on_sample = on_sample
        self.requests_dir, self.pick_request = requests_dir, pick_request
        self.selected_request: Path | None = None
        self.result: dict | None = None
        self.samples: list[Sample] = []
        self._started = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static("Waiting for first response", id="chart")
            yield Static(f"Completed 0/{self.count}", id="summary")
            yield Static("", id="timings")
            yield DataTable(id="results")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"tbench · {self.url} · {self.count} requests · concurrency {self.concurrency}"
        self._main_screen = self.screen
        self._main_screen.query_one("#results", DataTable).add_columns("#", "Status", "Time", "Note")
        self._main_screen.query_one("#timings", Static).display = False
        if self.pick_request:
            self.push_screen(RequestScreen(self.requests_dir))
        else:
            self.start_measurement()

    def action_show_history(self) -> None:
        self.push_screen(HistoryScreen())

    def action_show_compare(self) -> None:
        self.push_screen(CompareScreen())

    def start_measurement(self) -> None:
        if not self._started:
            self._started = True
            self.run_worker(self._measure, thread=True)

    def _measure(self) -> None:
        def received(sample: Sample, summary: dict) -> None:
            if self.on_sample:
                self.on_sample(sample)
            self.call_from_thread(self._show_sample, sample, summary)

        self.result = run(
            self.url, self.body, self.headers, self.count, self.timeout, self.warmup,
            received,
            self.concurrency,
        )

    def _show_sample(self, sample: Sample, summary: dict) -> None:
        self.samples.append(sample)
        note = ", ".join(part for part in ("first call" if sample.number == 1 else "", sample.error_kind or "") if part)
        self._main_screen.query_one("#results", DataTable).add_row(
            str(sample.number), str(sample.status or "—"), f"{sample.seconds:.3f}s",
            note,
        )
        self._main_screen.query_one("#chart", Static).update(sparkline([item.seconds for item in self.samples]))
        self._main_screen.query_one("#summary", Static).update(
            f"Completed {summary['count']}/{self.count}  Failures {summary['failures']}  "
            f"p50 {seconds(summary['p50'])}  p95 {seconds(summary['p95'])}  max {seconds(summary['max'])}  "
            f"First-excluded p50 {seconds(summary['p50_without_first'])}"
        )
        timings = self._main_screen.query_one("#timings", Static)
        if summary["timings_ms"]:
            timings.update("timings mean (ms): " + ", ".join(
                f"{key}={value:.1f}" for key, value in summary["timings_ms"].items()
            ))
            timings.display = True
