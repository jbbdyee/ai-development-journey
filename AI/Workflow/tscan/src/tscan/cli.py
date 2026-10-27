from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tscan.git import get_repo_root, scan_staged
from tscan.hooks import install_hook, uninstall_hook
from tscan.models import ScanSummary
from tscan.scanner import scan_folder


def print_plain(summary: ScanSummary) -> None:
    if not summary.findings:
        return
    print(f"{'종류':<12} {'파일':<38} {'줄':<4} {'값'}")
    for f in summary.findings:
        print(f"{f.kind:<12} {f.path:<38} {f.line:<4} {f.masked}")


def print_json(summary: ScanSummary) -> None:
    print(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))


def print_summary(summary: ScanSummary) -> None:
    print("--------------------------------------------------")
    print("검사 요약 (Summary):")
    print(f"  검사한 파일: {summary.scanned_files}")
    print(f"  건너뛴 파일: {summary.skipped_files}")
    print(f"  발견된 비밀: {len(summary.findings)}")
    if summary.findings_by_kind:
        print("  종류별 현황:")
        for kind, count in sorted(summary.findings_by_kind.items()):
            print(f"    - {kind}: {count}")
    if summary.findings_by_file:
        print("  파일별 현황:")
        for path, count in sorted(summary.findings_by_file.items()):
            print(f"    - {path}: {count}")
    print("--------------------------------------------------")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="tscan",
        description="A terminal secret and PII scanner for git repositories and directories",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to execute")

    # scan subcommand
    scan_parser = subparsers.add_parser("scan", help="Scan a directory or file for secrets")
    scan_parser.add_argument("target", nargs="?", default=".", help="Target path to scan")
    scan_parser.add_argument("--plain", action="store_true", help="Output findings in plain text format")
    scan_parser.add_argument("--json", action="store_true", help="Output findings in JSON format")
    scan_parser.add_argument("--summary", action="store_true", help="Output summary statistics")

    # staged subcommand
    staged_parser = subparsers.add_parser("staged", help="Scan git staged changes only")
    staged_parser.add_argument("--plain", action="store_true", default=True, help="Output plain text")
    staged_parser.add_argument("--json", action="store_true", help="Output findings in JSON format")
    staged_parser.add_argument("--summary", action="store_true", help="Output summary statistics")

    # install-hook subcommand
    subparsers.add_parser("install-hook", help="Install pre-commit hook")

    # uninstall-hook subcommand
    subparsers.add_parser("uninstall-hook", help="Uninstall pre-commit hook")

    # history subcommand (for Stage 4)
    history_parser = subparsers.add_parser("history", help="Scan git commit history for leaked secrets")
    history_parser.add_argument("--json", action="store_true", help="Output in JSON format")

    # If first argument looks like a path or flag (and not a known subcommand), default to 'scan'
    known_subcommands = {"scan", "staged", "install-hook", "uninstall-hook", "history"}
    if argv and argv[0] not in known_subcommands and not argv[0].startswith("-h") and not argv[0].startswith("--h"):
        argv = ["scan"] + argv

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code != 0 else 0

    if args.subcommand == "scan":
        target = Path(args.target)
        if not target.exists():
            sys.stderr.write(f"Error: Target path '{args.target}' does not exist.\n")
            return 2

        summary = scan_folder(target)

        if args.json:
            print_json(summary)
            return 1 if summary.findings else 0
        elif args.plain or args.summary:
            if args.plain or not args.summary:
                print_plain(summary)
            if args.summary:
                print_summary(summary)
            return 1 if summary.findings else 0
        else:
            try:
                from tscan.app import TScanApp
                app = TScanApp(summary=summary, target_path=str(target))
                app.run()
                return 0
            except ImportError:
                print_plain(summary)
                return 1 if summary.findings else 0

    elif args.subcommand == "staged":
        repo_root = get_repo_root()
        if not repo_root:
            sys.stderr.write("Error: Not a git repository.\n")
            return 2

        summary = scan_staged(repo_root)

        if args.json:
            print_json(summary)
            return 1 if summary.findings else 0
        else:
            print_plain(summary)
            if args.summary:
                print_summary(summary)
            return 1 if summary.findings else 0

    elif args.subcommand == "install-hook":
        success, msg = install_hook()
        if success:
            print(msg)
            return 0
        else:
            sys.stderr.write(f"{msg}\n")
            return 1

    elif args.subcommand == "uninstall-hook":
        success, msg = uninstall_hook()
        if success:
            print(msg)
            return 0
        else:
            sys.stderr.write(f"{msg}\n")
            return 1

    elif args.subcommand == "history":
        from tscan.history import scan_history  # Will be implemented in Stage 4
        repo_root = get_repo_root()
        if not repo_root:
            sys.stderr.write("Error: Not a git repository.\n")
            return 2
        history_findings = scan_history(repo_root)
        if getattr(args, "json", False):
            print(json.dumps([h.to_dict() for h in history_findings], indent=2, ensure_ascii=False))
        else:
            if not history_findings:
                print("과거 커밋에서 유출된 비밀이 없습니다. (Clean)")
            else:
                print(f"{'커밋':<10} {'종류':<12} {'파일':<34} {'값'}")
                for h in history_findings:
                    print(f"{h.commit_hash:<10} {h.kind:<12} {h.path:<34} {h.masked}")
        return 1 if history_findings else 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
