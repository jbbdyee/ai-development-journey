import json
import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tbench.engine import Sample, compare, passes_limits, percentile, redact_headers, run, save_result, summarize
from tbench import engine
from tbench.cli import main
from tbench.engine import extract_timings
from tbench.storage import history, load_profiles, log_sample
from tbench.tui import BenchmarkApp
from textual.widgets import DataTable, Static
import httpx


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


@pytest.fixture
def server():
    class Handler(BaseHTTPRequestHandler):
        lock = threading.Lock()
        counter = 0
        received_headers = []

        def do_POST(self):
            with type(self).lock:
                type(self).counter += 1
                request_number = type(self).counter
                type(self).received_headers.append(dict(self.headers))
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            if self.path == "/vary":
                time.sleep((0.05, 0.2, 0.4)[(request_number - 1) % 3])
            if self.path == "/slow":
                time.sleep(0.15)
            if self.path == "/first-slow" and request_number == 1:
                time.sleep(0.15)
            status = 500 if self.path == "/every-third" and request_number % 3 == 0 else 200
            if self.path == "/not-found":
                status = 404
            data = json.dumps({"ok": True} if self.path == "/no-timings" else
                              {"timings": {"answer_ms": 12, "total_ms": 15}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except BrokenPipeError:
                pass

        def log_message(self, *_):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", Handler
    finally:
        httpd.shutdown()
        thread.join()
        httpd.server_close()


@pytest.fixture
def concurrency_server():
    class Handler(BaseHTTPRequestHandler):
        lock = threading.Lock()
        active = 0
        peak = 0
        started = 0

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            with type(self).lock:
                type(self).active += 1
                type(self).started += 1
                request_number = type(self).started
                type(self).peak = max(type(self).peak, type(self).active)
            try:
                time.sleep(0.35 if self.path == "/stagger" and request_number == 1 else 0.3 if self.path == "/delay" else 0.05)
                status = 500 if self.path == "/fail" else 200
                self.send_response(status)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")
            finally:
                with type(self).lock:
                    type(self).active -= 1

        def log_message(self, *_):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", Handler
    finally:
        httpd.shutdown()
        thread.join()
        httpd.server_close()


def test_concurrency_limit_speed_and_completion_order(concurrency_server, monkeypatch):
    base, handler = concurrency_server
    began = time.perf_counter()
    sequential = run(base + "/delay", b"{}", {}, 6, concurrency=1)
    sequential_time = time.perf_counter() - began
    assert handler.peak == 1
    assert [sample["number"] for sample in sequential["samples"]] == list(range(1, 7))

    handler.peak = 0
    began = time.perf_counter()
    concurrent = run(base + "/delay", b"{}", {}, 6, concurrency=3)
    concurrent_time = time.perf_counter() - began
    assert handler.peak == 3
    assert concurrent["concurrency"] == 3
    assert sorted(sample["number"] for sample in concurrent["samples"]) == list(range(1, 7))
    assert sequential_time > concurrent_time * 1.8

    original_request_once = engine.request_once

    def delayed_first(*args):
        sample = original_request_once(*args)
        if sample.number == 1:
            time.sleep(0.5)
        return sample

    monkeypatch.setattr(engine, "request_once", delayed_first)
    arrivals = []
    staggered = run(base + "/", b"{}", {}, 3, concurrency=3, on_sample=lambda sample, _: arrivals.append(sample.number))
    assert sorted(arrivals) == [1, 2, 3]
    assert arrivals[0] != 1
    assert [sample["number"] for sample in staggered["samples"]] == arrivals


def test_nearest_rank_and_first_excluded():
    assert percentile(list(range(1, 11)), 0.5) == 5
    assert percentile(list(range(1, 11)), 0.95) == 10
    samples = [Sample(1, "", 200, 2), Sample(2, "", 200, 0.1), Sample(3, "", 500, 0.2, "http_5xx")]
    summary = summarize(samples)
    assert summary["p50"] == 0.1
    assert summary["p50_without_first"] == 0.1
    assert summary["failures"] == 1


def test_compare_percentages_and_zero_baseline():
    before = {"url": "http://example.test", "body_sha256": None, "count": 2,
              "summary": {"p50": 1.0, "p95": 2.0, "max": 2.0, "failures": 0}}
    after = {**before, "summary": {"p50": 0.5, "p95": 3.0, "max": 3.0, "failures": 1}}
    report = compare(before, after)
    assert report["warnings"] == []
    assert report["metrics"]["p50"]["change_percent"] == -50
    assert report["metrics"]["p95"]["change_percent"] == 50
    assert report["metrics"]["failures"]["change_percent"] is None


def test_limit_policy():
    successful = {"successes": 2, "p95": 0.3, "failures": 0}
    assert passes_limits(successful, None, None) is None
    assert passes_limits(successful, 0.3, 0) is True
    assert passes_limits(successful, 0.2, 0) is False
    assert passes_limits(successful, 1, -1) is False
    no_success = {"successes": 0, "p95": None, "failures": 2}
    assert passes_limits(no_success, None, 2) is False
    assert passes_limits(no_success, 1, None) is False
    assert passes_limits(no_success, None, None) is None


def test_timings_missing_and_non_numeric_values():
    response = httpx.Response(200, content=json.dumps({"timings": {
        "classify_ms": 10, "data_ms": 20.5, "answer_ms": "30",
        "review_ms": None, "total_ms": 31, "flag_ms": True, "bad_ms": float("nan"),
        "other": 99,
    }}).encode())
    assert extract_timings(response) == {"classify_ms": 10, "data_ms": 20.5, "total_ms": 31}
    assert extract_timings(httpx.Response(200, json={"answer": "ok"})) is None
    assert extract_timings(httpx.Response(200, text="not json")) is None
    samples = [Sample(1, "", 200, 0.1, timings={"data_ms": 10, "total_ms": 30}),
               Sample(2, "", 200, 0.2, timings={"total_ms": 50})]
    assert summarize(samples)["timings_ms"] == {"data_ms": 10, "total_ms": 40}


def test_requests_failure_kinds_and_warmup(server):
    base, handler = server
    body = b'{"question":"vpn"}'
    results = []
    result = run(base + "/every-third", body, {}, 6, on_sample=lambda sample, _: results.append(sample))
    assert len(results) == 6
    assert result["summary"]["failure_kinds"] == {"http_5xx": 2}
    assert result["summary"]["timings_ms"] == {"answer_ms": 12, "total_ms": 15}
    assert run(base + "/not-found", body, {}, 1)["summary"]["failure_kinds"] == {"http_4xx": 1}
    count_before = handler.counter
    assert len(run(base + "/", body, {}, 2, warmup=1)["samples"]) == 2
    assert handler.counter - count_before == 3


def test_first_call_is_slow_and_excluded(server):
    base, _ = server
    result = run(base + "/first-slow", b"{}", {}, 3)
    assert result["samples"][0]["number"] == 1
    assert result["samples"][0]["seconds"] > result["samples"][1]["seconds"] + 0.1
    assert result["summary"]["p50_without_first"] is not None
    assert result["summary"]["max"] == result["samples"][0]["seconds"]


def test_timeout_and_connect(server):
    base, _ = server
    assert run(base + "/slow", b"{}", {}, 1, timeout=0.01)["summary"]["failure_kinds"] == {"timeout": 1}
    assert run("http://127.0.0.1:1/", b"{}", {}, 1, timeout=0.1)["summary"]["failure_kinds"] == {"connect": 1}


def test_redaction_save_and_compare(tmp_path, server):
    base, handler = server
    headers = {"Authorization": "Bearer sk-test", "X-API-Key": "secret", "Accept": "application/json"}
    assert redact_headers(headers) == {"Authorization": "***", "X-API-Key": "***", "Accept": "application/json"}
    before = run(base + "/", b"{}", headers, 2)
    assert handler.received_headers[0]["Authorization"] == "Bearer sk-test"
    path = tmp_path / "result.json"
    save_result(before, path)
    assert "sk-test" not in path.read_text()
    saved = json.loads(path.read_text())
    assert saved["url"] == base + "/"
    assert saved["method"] == "POST"
    assert saved["body_sha256"] and saved["count"] == 2
    assert saved["concurrency"] == 1 and saved["warmup"] == 0
    assert saved["started_at"] and saved["timeout"] == 30
    assert len(saved["samples"]) == 2
    after = run(base + "/", b'{"other":true}', headers, 2)
    assert compare(before, after)["warnings"] == ["body hash"]
    changed = dict(after, url="http://different.test/", count=3)
    assert compare(before, changed)["warnings"] == ["URL", "body hash", "N"]
    report = compare(before, before)
    assert all(values["change_percent"] == 0 for values in report["metrics"].values() if values["before"] != 0)


def test_plain_cli_warmup_headers_save_and_compare(tmp_path, server, capsys):
    base, _ = server
    body = tmp_path / "body.json"
    body.write_text('{"question":"vpn"}')
    saved = tmp_path / "before.json"
    assert main([
        base + "/every-third", "--body-file", str(body), "-n", "6", "--warmup", "1",
        "--header", "Authorization: Bearer sk-test", "--header", "X-API-Key: key-test",
        "--plain", "--save", str(saved),
    ]) == 0
    output = capsys.readouterr().out
    assert "first call" in output
    assert "completed 6" in output
    assert "p50" in output and "p95" in output and "max" in output
    assert "http_5xx=2" in output
    assert "sk-test" not in saved.read_text()
    assert "key-test" not in saved.read_text()
    payload = json.loads(saved.read_text())
    assert len(payload["samples"]) == 6
    assert payload["headers"]["Authorization"] == "***"
    assert payload["headers"]["X-API-Key"] == "***"
    assert payload["warmup"] == 1

    other_body = tmp_path / "other.json"
    other_body.write_text('{"question":"different"}')
    after = tmp_path / "after.json"
    assert main([base + "/every-third", "--body-file", str(other_body), "-n", "6", "--plain", "--save", str(after)]) == 0
    capsys.readouterr()
    assert main(["compare", str(saved), str(after)]) == 0
    compared = capsys.readouterr().out
    assert "WARNING: different URL" not in compared
    assert "WARNING: different body hash" in compared
    assert all(name in compared for name in ("p50", "p95", "max", "failures"))


def test_jsonl_log_is_one_line_per_measured_call_and_has_no_secret(tmp_path, server):
    base, _ = server
    body = tmp_path / "body.json"
    body.write_text("{}")
    log = tmp_path / "records.jsonl"
    assert main([base + "/every-third", "--body-file", str(body), "-n", "6",
                 "--warmup", "1", "--concurrency", "2", "--plain",
                 "--header", "Authorization: Bearer sk-test", "--header", "X-API-Key: secret-test",
                 "--log", str(log)]) == 0
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(records) == 6
    assert sorted(row["number"] for row in records) == list(range(1, 7))
    assert all(set(row) == {"timestamp", "number", "status", "seconds", "error_kind"} for row in records)
    assert all(row["timestamp"] and row["seconds"] >= 0 for row in records)
    assert sum(row["error_kind"] == "http_5xx" for row in records) == 2
    assert "sk-test" not in log.read_text() and "secret-test" not in log.read_text()


def test_plain_timings_line_is_hidden_without_timings(tmp_path, server, capsys):
    base, _ = server
    body = tmp_path / "body.json"
    body.write_text("{}")
    assert main([base + "/", "--body-file", str(body), "-n", "1", "--plain"]) == 0
    assert "timings mean (ms): answer_ms=12.0, total_ms=15.0" in capsys.readouterr().out
    assert main([base + "/no-timings", "--body-file", str(body), "-n", "1", "--plain"]) == 0
    assert "timings mean" not in capsys.readouterr().out


def test_profile_reuses_absolute_body_path_from_other_directory(tmp_path, monkeypatch, server, capsys):
    base, handler = server
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    body = first / "body.json"
    body.write_text('{"question":"vpn"}')
    monkeypatch.chdir(first)
    assert main(["profile", "save", "vpn", base + "/", "--body-file", "body.json",
                 "-n", "2", "--warmup", "1"]) == 0
    profile = load_profiles()["vpn"]
    assert profile["body_file"] == str(body)
    monkeypatch.chdir(second)
    assert main(["run", "vpn", "--plain"]) == 0
    output = capsys.readouterr().out
    assert "completed 2" in output
    assert handler.counter == 3
    assert all(row.get("Content-Type") == "application/json" for row in handler.received_headers)
    assert len(history()) == 1


def test_profile_does_not_store_credentials(tmp_path, server, capsys):
    base, handler = server
    body = tmp_path / "body.json"
    body.write_text("{}")
    assert main(["profile", "save", "safe", base + "/", "--body-file", str(body), "-n", "1"]) == 0
    assert main(["run", "safe", "--plain", "--header", "Authorization: Bearer sk-test"]) == 0
    profile_text = (tmp_path / "home" / ".tbench" / "profiles.json").read_text()
    assert "sk-test" not in profile_text and "Authorization" not in profile_text
    assert handler.received_headers[0]["Authorization"] == "Bearer sk-test"
    with pytest.raises(SystemExit):
        main(["profile", "save", "unsafe", base + "/?token=sk-test"])
    assert "sk-test" not in profile_text


def test_history_is_newest_first_and_skips_broken_files(tmp_path, server, capsys):
    base, _ = server
    body = tmp_path / "body.json"
    body.write_text("{}")
    home = tmp_path / "home"
    assert main(["history"]) == 0
    assert "No saved runs" in capsys.readouterr().out
    runs = home / ".tbench" / "runs"
    runs.mkdir(parents=True)
    (runs / "broken.json").write_text("not json")
    (runs / "incomplete.json").write_text('{"started_at":"2026-01-01"}')
    assert main([base + "/", "--body-file", str(body), "-n", "1", "--plain"]) == 0
    assert main([base + "/", "--body-file", str(body), "-n", "2", "--plain"]) == 0
    assert len(history()) == 2
    assert main(["history"]) == 0
    listed = capsys.readouterr().out.split("date                         URL  N  p50  p95  failures")[-1]
    rows = [line for line in listed.splitlines() if base in line]
    assert len(rows) == 2
    assert "  2  " in rows[0] and "  1  " in rows[1]


def test_cli_limits_pass_fail_and_no_success(concurrency_server, tmp_path, capsys):
    base, _ = concurrency_server
    body = tmp_path / "body.json"
    body.write_text("{}")
    common = ["--body-file", str(body), "-n", "2", "--concurrency", "2", "--plain"]
    assert main([base + "/delay", *common, "--max-p95", "1", "--max-failures", "0"]) == 0
    assert "PASS" in capsys.readouterr().out
    assert main([base + "/delay", *common, "--max-p95", "0.01"]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert main([base + "/fail", *common, "--max-failures", "2"]) == 1
    output = capsys.readouterr().out
    assert "failures 2" in output and "FAIL" in output
    assert main([base + "/delay", *common]) == 0
    assert "PASS" not in capsys.readouterr().out


def test_tui_concurrent_completion_order(concurrency_server, monkeypatch):
    base, _ = concurrency_server
    original_request_once = engine.request_once

    def delayed_first(*args):
        sample = original_request_once(*args)
        if sample.number == 1:
            time.sleep(0.5)
        return sample

    monkeypatch.setattr(engine, "request_once", delayed_first)

    async def check():
        app = BenchmarkApp(base + "/", b"{}", {}, 3, 1, 0, 3)
        async with app.run_test() as pilot:
            deadline = time.monotonic() + 3
            while app.query_one(DataTable).row_count < 3 and time.monotonic() < deadline:
                await pilot.pause(0.03)
            assert app.query_one(DataTable).row_count == 3
            assert sorted(sample.number for sample in app.samples) == [1, 2, 3]
            assert app.samples[0].number != 1
            assert "Completed 3/3" in str(app.query_one("#summary", Static).render())
            await pilot.press("q")

    asyncio.run(check())


def test_tui_updates_before_completion(server):
    base, _ = server
    async def check():
        app = BenchmarkApp(base + "/slow", b"{}", {}, 5, 1, 0)
        async with app.run_test() as pilot:
            table = app.query_one(DataTable)
            deadline = time.monotonic() + 3
            while table.row_count == 0 and time.monotonic() < deadline:
                await pilot.pause(0.03)
            assert table.row_count >= 1
            assert table.row_count < 5
            assert app.result is None
            assert "Completed 1/5" in str(app.query_one("#summary", Static).render())
            assert str(app.query_one("#chart", Static).render()) in "▁▂▃▄▅▆▇█"
            while table.row_count < 5 and time.monotonic() < deadline:
                await pilot.pause(0.03)
            assert table.row_count == 5
            assert "Completed 5/5" in str(app.query_one("#summary", Static).render())
            assert len(app.samples) == 5
            await pilot.press("q")

    asyncio.run(check())


def test_tui_sparkline_varies_with_response_time(server):
    base, _ = server

    async def check():
        app = BenchmarkApp(base + "/vary", b"{}", {}, 3, 1, 0)
        async with app.run_test() as pilot:
            deadline = time.monotonic() + 3
            while app.query_one(DataTable).row_count < 3 and time.monotonic() < deadline:
                await pilot.pause(0.03)
            assert app.query_one(DataTable).row_count == 3
            chart = str(app.query_one("#chart", Static).render())
            assert len(chart) == 3
            assert len(set(chart)) >= 3
            assert chart[-1] == "█"
            await pilot.press("q")

    asyncio.run(check())


def test_tui_timings_are_shown_only_when_present(server):
    base, _ = server

    async def check(path: str, expected: bool):
        app = BenchmarkApp(base + path, b"{}", {}, 2, 1, 0)
        async with app.run_test() as pilot:
            deadline = time.monotonic() + 3
            while app.query_one(DataTable).row_count < 2 and time.monotonic() < deadline:
                await pilot.pause(0.03)
            timings = app.query_one("#timings", Static)
            assert timings.display is expected
            if expected:
                assert "answer_ms=12.0" in str(timings.render())
                assert "total_ms=15.0" in str(timings.render())
            await pilot.press("q")

    asyncio.run(check("/", True))
    asyncio.run(check("/no-timings", False))


def test_tui_writes_jsonl_as_results_arrive(tmp_path, server):
    base, _ = server
    log = tmp_path / "tui.jsonl"

    async def check():
        app = BenchmarkApp(base + "/slow", b"{}", {}, 3, 1, 0,
                           on_sample=lambda sample: log_sample(log, sample))
        async with app.run_test() as pilot:
            deadline = time.monotonic() + 3
            while app.query_one(DataTable).row_count == 0 and time.monotonic() < deadline:
                await pilot.pause(0.03)
            assert len(log.read_text().splitlines()) >= 1
            while app.query_one(DataTable).row_count < 3 and time.monotonic() < deadline:
                await pilot.pause(0.03)
            assert len(log.read_text().splitlines()) == 3
            await pilot.press("q")

    asyncio.run(check())


def test_tui_quit_while_running(server):
    base, _ = server

    async def check():
        app = BenchmarkApp(base + "/slow", b"{}", {}, 5, 1, 0)
        async with app.run_test() as pilot:
            deadline = time.monotonic() + 3
            while app.query_one(DataTable).row_count == 0 and time.monotonic() < deadline:
                await pilot.pause(0.03)
            assert app.query_one(DataTable).row_count > 0
            assert app.result is None
            await pilot.press("q")

    asyncio.run(check())
