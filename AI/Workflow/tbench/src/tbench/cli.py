"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from .engine import Sample, compare, passes_limits, run, save_result
from .storage import history, load_profiles, log_sample, save_default_result, save_profile


def seconds(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}s"


def add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("url", help="HTTP URL to measure")
    parser.add_argument("--body-file", type=Path, help="JSON request body file")
    parser.add_argument("--pick-request", action="store_true", help="choose a JSON body in the TUI before measuring")
    parser.add_argument("--requests-dir", type=Path, default=Path("requests"), help="directory shown by --pick-request (default: requests)")
    parser.add_argument("-n", "--count", type=int, default=10, help="measured request count")
    parser.add_argument("--timeout", type=float, default=30, help="request timeout in seconds")
    parser.add_argument("--warmup", type=int, default=0, help="unmeasured requests before the run")
    parser.add_argument("--header", action="append", default=[], metavar="K: V")
    parser.add_argument("--plain", action="store_true", help="text output instead of TUI")
    parser.add_argument("--save", type=Path, help="save result as JSON")
    parser.add_argument("--log", type=Path, help="append one JSON line per measured request")
    parser.add_argument("--concurrency", type=int, default=1, metavar="K", help="maximum concurrent requests")
    parser.add_argument("--max-p95", type=float, metavar="SECONDS", help="maximum allowed p95 seconds")
    parser.add_argument("--max-failures", type=int, metavar="N", help="maximum allowed failures")


def print_sample(sample: Sample, _: dict) -> None:
    note = ", ".join(part for part in ("first call" if sample.number == 1 else "", sample.error_kind or "") if part)
    print(f"{sample.number:>3}  {str(sample.status or '-'):>3}  {seconds(sample.seconds):>9}  {note}", flush=True)


def print_summary(summary: dict) -> None:
    print(
        f"completed {summary['count']}  failures {summary['failures']}  "
        f"p50 {seconds(summary['p50'])}  p95 {seconds(summary['p95'])}  "
        f"max {seconds(summary['max'])}  first-excluded p50 {seconds(summary['p50_without_first'])}"
    )
    if summary["failure_kinds"]:
        print("failure kinds: " + ", ".join(f"{key}={value}" for key, value in summary["failure_kinds"].items()))
    if summary["timings_ms"]:
        print("timings mean (ms): " + ", ".join(f"{key}={value:.1f}" for key, value in summary["timings_ms"].items()))


def run_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.count < 1 or not math.isfinite(args.timeout) or args.timeout <= 0 or args.warmup < 0 or args.concurrency < 1:
        parser.error("count, timeout and concurrency must be positive; warmup must be nonnegative")
    if args.max_p95 is not None and (not math.isfinite(args.max_p95) or args.max_p95 < 0):
        parser.error("max-p95 must be a finite nonnegative number")
    if args.max_failures is not None and args.max_failures < 0:
        parser.error("max-failures must be nonnegative")
    pick_request = getattr(args, "pick_request", False)
    if pick_request and (args.plain or args.body_file):
        parser.error("--pick-request requires TUI mode and cannot be used with --body-file")
    headers = {}
    for item in args.header:
        if ":" not in item:
            parser.error(f"invalid header {item!r}: expected K: V")
        key, value = item.split(":", 1)
        if not key.strip():
            parser.error("header name cannot be empty")
        headers[key.strip()] = value.strip()
    body = None
    if args.body_file:
        try:
            body = args.body_file.read_bytes()
            json.loads(body)
        except (OSError, ValueError) as exc:
            parser.error(f"cannot read JSON body: {exc}")
        headers.setdefault("Content-Type", "application/json")
    def received(sample: Sample, summary: dict) -> None:
        if args.plain:
            print_sample(sample, summary)
        if args.log:
            log_sample(args.log, sample)

    if args.plain:
        result = run(args.url, body, headers, args.count, args.timeout, args.warmup, received, args.concurrency)
        print_summary(result["summary"])
    else:
        from .tui import BenchmarkApp

        app = BenchmarkApp(args.url, body, headers, args.count, args.timeout, args.warmup, args.concurrency,
                           lambda sample: received(sample, {}),
                           requests_dir=getattr(args, "requests_dir", Path("requests")), pick_request=pick_request)
        app.run()
        result = app.result
        if result is None:
            return 130
    saved = args.save or save_default_result(result)
    if args.save:
        save_result(result, saved)
    print(f"saved {saved}")
    passed = passes_limits(result["summary"], args.max_p95, args.max_failures)
    if passed is not None:
        print("PASS" if passed else "FAIL")
    return 0 if passed is not False else 1


def compare_command(before_path: Path, after_path: Path) -> int:
    try:
        before = json.loads(before_path.read_text(encoding="utf-8"))
        after = json.loads(after_path.read_text(encoding="utf-8"))
        report = compare(before, after)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"cannot compare results: {exc}", file=sys.stderr)
        return 2
    if report["warnings"]:
        print("WARNING: different " + ", ".join(report["warnings"]))
    print("metric       before       after      change")
    for key, values in report["metrics"].items():
        old, new, change = values.values()
        fmt = str if key == "failures" else seconds
        change_text = "—" if change is None else f"{change:+.1f}%"
        print(f"{key:<10} {fmt(old):>10} {fmt(new):>10} {change_text:>10}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "compare":
        compare_parser = argparse.ArgumentParser(prog="tbench compare")
        compare_parser.add_argument("before", type=Path)
        compare_parser.add_argument("after", type=Path)
        compare_args = compare_parser.parse_args(argv[1:])
        return compare_command(compare_args.before, compare_args.after)
    if argv and argv[0] == "history":
        history_parser = argparse.ArgumentParser(prog="tbench history")
        history_parser.parse_args(argv[1:])
        rows = history()
        if not rows:
            print("No saved runs")
        else:
            print("date                         URL  N  p50  p95  failures")
            for row in rows:
                print(f"{row['started_at']}  {row['url']}  {row['count']}  "
                      f"{seconds(row['p50'])}  {seconds(row['p95'])}  {row['failures']}")
        return 0
    if argv[:2] == ["profile", "save"]:
        profile_parser = argparse.ArgumentParser(prog="tbench profile save")
        profile_parser.add_argument("name")
        profile_parser.add_argument("url")
        profile_parser.add_argument("--body-file", type=Path)
        profile_parser.add_argument("-n", "--count", type=int, default=10)
        profile_parser.add_argument("--timeout", type=float, default=30)
        profile_parser.add_argument("--warmup", type=int, default=0)
        profile_parser.add_argument("--concurrency", type=int, default=1)
        profile_args = profile_parser.parse_args(argv[2:])
        if (profile_args.count < 1 or profile_args.concurrency < 1 or profile_args.warmup < 0
                or not math.isfinite(profile_args.timeout) or profile_args.timeout <= 0):
            profile_parser.error("count, timeout and concurrency must be positive; warmup must be nonnegative")
        if profile_args.body_file:
            try:
                json.loads(profile_args.body_file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                profile_parser.error(f"cannot read JSON body: {exc}")
        profile = {"url": profile_args.url,
                   "body_file": str(profile_args.body_file.resolve()) if profile_args.body_file else None,
                   "count": profile_args.count, "timeout": profile_args.timeout,
                   "warmup": profile_args.warmup, "concurrency": profile_args.concurrency}
        try:
            path = save_profile(profile_args.name, profile)
        except (OSError, ValueError) as exc:
            profile_parser.error(str(exc))
        print(f"saved profile {profile_args.name} to {path}")
        return 0
    if argv and argv[0] == "run":
        profile_parser = argparse.ArgumentParser(prog="tbench run")
        profile_parser.add_argument("name")
        profile_parser.add_argument("--plain", action="store_true")
        profile_parser.add_argument("--header", action="append", default=[])
        profile_parser.add_argument("--save", type=Path)
        profile_parser.add_argument("--log", type=Path)
        profile_parser.add_argument("--max-p95", type=float)
        profile_parser.add_argument("--max-failures", type=int)
        profile_args = profile_parser.parse_args(argv[1:])
        try:
            profile = load_profiles()[profile_args.name]
        except (OSError, ValueError, KeyError) as exc:
            profile_parser.error(f"cannot load profile: {exc}")
        args = argparse.Namespace(**profile, plain=profile_args.plain, header=profile_args.header,
                                  save=profile_args.save, log=profile_args.log,
                                  max_p95=profile_args.max_p95, max_failures=profile_args.max_failures)
        args.body_file = Path(args.body_file) if args.body_file else None
        return run_command(args, profile_parser)
    parser = argparse.ArgumentParser(prog="tbench", description="Measure HTTP webhook response times")
    parser.epilog = "Commands: compare BEFORE AFTER, history, profile save NAME URL, run NAME"
    add_run_arguments(parser)
    args = parser.parse_args(argv)
    if not args.url:
        parser.error("a URL is required")
    return run_command(args, parser)


if __name__ == "__main__":
    raise SystemExit(main())
