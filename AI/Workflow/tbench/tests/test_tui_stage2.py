import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from textual.widgets import DataTable, Static

from tbench.cli import main
from tbench.engine import run
from tbench.storage import save_default_result
from tbench.tui import BenchmarkApp, CompareScreen, HistoryScreen, RequestScreen


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        bodies = []
        content_types = []

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            type(self).bodies.append(self.rfile.read(length))
            type(self).content_types.append(self.headers.get("Content-Type"))
            if self.path == "/slow":
                time.sleep(0.15)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/", Handler
    finally:
        httpd.shutdown()
        thread.join()
        httpd.server_close()


async def wait_for(pilot, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        await pilot.pause(0.03)
    assert predicate()


def test_request_picker_uses_selected_json_and_rejects_bad_file(tmp_path, server):
    url, handler = server
    directory = tmp_path / "requests"
    directory.mkdir()
    (directory / "a-bad.json").write_text("{bad", encoding="utf-8")
    good = directory / "b-good.json"
    good.write_bytes(b'{"question":"chosen"}')

    async def check():
        app = BenchmarkApp(url, None, {}, 1, 1, 0, requests_dir=directory, pick_request=True)
        async with app.run_test() as pilot:
            assert isinstance(app.screen, RequestScreen)
            assert app.screen.query_one("#request_files", DataTable).row_count == 2
            await pilot.press("enter")
            assert "Cannot use a-bad.json" in str(app.screen.query_one("#request_status", Static).render())
            assert app.result is None and not handler.bodies
            await pilot.press("down", "enter")
            await wait_for(pilot, lambda: app.result is not None)
            assert app.selected_request == good
            assert handler.bodies == [good.read_bytes()]
            assert handler.content_types == ["application/json"]
            assert app.query_one("#results", DataTable).row_count == 1
            await pilot.press("q")

    asyncio.run(check())


def test_request_picker_empty_and_body_file_conflict(tmp_path, server):
    url, handler = server
    directory = tmp_path / "empty"
    directory.mkdir()

    async def check():
        app = BenchmarkApp(url, None, {}, 1, 1, 0, requests_dir=directory, pick_request=True)
        async with app.run_test() as pilot:
            assert "No JSON requests found" in str(app.screen.query_one("#request_status", Static).render())
            assert app.result is None and not handler.bodies
            await pilot.press("escape")
            assert not isinstance(app.screen, RequestScreen)
            await pilot.press("q")

    asyncio.run(check())
    body = tmp_path / "body.json"
    body.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        main([url, "--pick-request", "--body-file", str(body)])
    with pytest.raises(SystemExit):
        main([url, "--pick-request", "--plain"])


def test_tui_history_and_compare_warn_and_handle_missing_files(tmp_path, monkeypatch, server):
    url, _ = server
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    older = save_default_result(run(url, b'{"first":true}', {}, 1))
    newer = save_default_result(run(url, b'{"second":true}', {}, 2))
    older_result = json.loads(older.read_text(encoding="utf-8"))
    older_result["url"] = url + "changed"
    older.write_text(json.dumps(older_result), encoding="utf-8")
    runs = newer.parent
    (runs / "broken.json").write_text("{bad", encoding="utf-8")
    (runs / "incomplete.json").write_text('{"started_at":"2026-01-01"}', encoding="utf-8")
    malformed = dict(older_result)
    malformed["summary"] = dict(malformed["summary"], p50="not-a-number")
    (runs / "wrong-type.json").write_text(json.dumps(malformed), encoding="utf-8")
    empty_requests = tmp_path / "requests"
    empty_requests.mkdir()

    async def check():
        app = BenchmarkApp(url, None, {}, 1, 1, 0, requests_dir=empty_requests, pick_request=True)
        async with app.run_test() as pilot:
            await pilot.press("escape", "h")
            assert isinstance(app.screen, HistoryScreen)
            table = app.screen.query_one("#history_rows", DataTable)
            assert table.row_count == 2
            assert table.get_row_at(0)[2] == "2"
            assert table.get_row_at(1)[2] == "1"
            assert "Failures" in app.export_screenshot()
            assert url in str(app.screen.query_one("#history_status", Static).render())
            await pilot.press("enter")
            assert isinstance(app.screen, CompareScreen)
            assert app.screen.before == newer
            await pilot.press("down", "enter")
            metrics = app.screen.query_one("#compare_metrics", DataTable)
            assert metrics.row_count == 4
            assert [metrics.get_row_at(i)[0] for i in range(4)] == ["p50", "p95", "max", "failures"]
            assert "%" in str(metrics.get_row_at(0)[3])
            warning = str(app.screen.query_one("#compare_warning", Static).render())
            assert all(part in warning for part in ("URL", "body hash", "N"))
            await pilot.press("escape", "escape", "c")
            assert isinstance(app.screen, CompareScreen)
            assert app.screen.query_one("#compare_files", DataTable).row_count == 2
            await pilot.press("enter")
            newer.unlink()
            await pilot.press("down", "enter")
            assert "Cannot compare results" in str(app.screen.query_one("#compare_status", Static).render())
            await pilot.press("q")

    asyncio.run(check())


def test_tui_empty_history(tmp_path, monkeypatch, server):
    url, _ = server
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    directory = tmp_path / "empty"
    directory.mkdir()

    async def check():
        app = BenchmarkApp(url, None, {}, 1, 1, 0, requests_dir=directory, pick_request=True)
        async with app.run_test() as pilot:
            await pilot.press("escape", "h")
            assert "No saved runs" in str(app.screen.query_one("#history_status", Static).render())
            await pilot.press("escape", "c")
            assert "No saved runs" in str(app.screen.query_one("#compare_status", Static).render())
            await pilot.press("q")

    asyncio.run(check())


def test_tui_worker_keeps_updating_behind_history_screen(tmp_path, monkeypatch, server):
    url, _ = server
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    async def check():
        app = BenchmarkApp(url + "slow", b"{}", {}, 3, 1, 0)
        async with app.run_test() as pilot:
            await pilot.press("h")
            assert isinstance(app.screen, HistoryScreen)
            await wait_for(pilot, lambda: app.result is not None)
            await pilot.press("escape")
            assert app.query_one("#results", DataTable).row_count == 3
            assert "Completed 3/3" in str(app.query_one("#summary", Static).render())
            await pilot.press("q")

    asyncio.run(check())
