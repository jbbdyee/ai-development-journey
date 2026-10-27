import os
from pathlib import Path
import subprocess
from tscan.config import load_custom_rules
from tscan.ignore import IgnoreFilter
from tscan.models import ScanSummary
from tscan.scanner import (
    IGNORED_DIRS,
    MAX_FILE_SIZE,
    collect_env_values,
    scan_text,
)


def get_repo_root(cwd: Path | str | None = None) -> Path | None:
    """Get the root directory of the current git repository."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(res.stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_git_dir(cwd: Path | str | None = None) -> Path | None:
    """Get the .git directory path (handles normal repos and worktrees)."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        git_dir = Path(res.stdout.strip())
        if not git_dir.is_absolute():
            root = cwd if cwd else Path.cwd()
            git_dir = (Path(root) / git_dir).resolve()
        return git_dir
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_staged_files(repo_root: Path | None = None) -> list[str]:
    """Get list of staged files (Added, Copied, Modified) from git index."""
    try:
        res = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        return lines
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def get_staged_bytes(rel_path: str, repo_root: Path | None = None) -> bytes | None:
    """Get raw staged content of a file from git index using git show :<path>."""
    try:
        res = subprocess.run(
            ["git", "show", f":{rel_path}"],
            cwd=repo_root,
            capture_output=True,
            check=True,
        )
        return res.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def scan_staged(repo_root: Path | None = None) -> ScanSummary:
    """Scan only staged contents of git add-ed files."""
    summary = ScanSummary()
    root = repo_root or get_repo_root()
    if not root:
        return summary

    staged_files = get_staged_files(root)
    if not staged_files:
        return summary

    env_values, _ = collect_env_values(root)
    custom_patterns = load_custom_rules(root)

    for rel_path in staged_files:
        # Check ignored directories
        parts = Path(rel_path).parts
        if any(part in IGNORED_DIRS for part in parts):
            summary.skipped_files += 1
            continue

        raw_bytes = get_staged_bytes(rel_path, root)
        if raw_bytes is None:
            summary.skipped_files += 1
            continue

        # Size check
        if len(raw_bytes) > MAX_FILE_SIZE:
            summary.skipped_files += 1
            continue

        # Binary check (NUL byte in first 1024 bytes)
        if b"\x00" in raw_bytes[:1024]:
            summary.skipped_files += 1
            continue

        try:
            content = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            summary.skipped_files += 1
            continue

        summary.scanned_files += 1
        fname = Path(rel_path).name
        is_env = fname == ".env" or fname.startswith(".env.")
        findings = scan_text(
            content,
            rel_path,
            env_values,
            is_env_file=is_env,
            custom_patterns=custom_patterns,
        )
        summary.findings.extend(findings)

    ignore_file = root / ".tscanignore"
    if ignore_file.exists():
        filt = IgnoreFilter.load(ignore_file)
        summary.findings = filt.filter_findings(summary.findings)

    return summary
