import os
from pathlib import Path
import re
from tscan.config import load_custom_rules
from tscan.ignore import IgnoreFilter
from tscan.masker import mask_line, mask_value
from tscan.models import Finding, ScanSummary
from tscan.patterns import PATTERNS

IGNORED_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".uv-cache",
}

MAX_FILE_SIZE = 1024 * 1024  # 1MB


def is_binary_file(path: Path) -> bool:
    """Check if file is binary by searching for NUL byte in the first 1024 bytes."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
            return b"\x00" in chunk
    except OSError:
        return True


def collect_env_values(root_path: Path) -> tuple[set[str], set[Path]]:
    """Collect secret values (>= 6 chars) from .env files in root_path."""
    env_values: set[str] = set()
    env_files: set[Path] = set()

    if root_path.is_file():
        candidates = [root_path] if root_path.name.startswith(".env") else []
    else:
        candidates = []
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
            for fname in filenames:
                if fname == ".env" or fname.startswith(".env."):
                    candidates.append(Path(dirpath) / fname)

    for env_file in candidates:
        env_files.add(env_file.resolve())
        try:
            with open(env_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    _, val = line.split("=", 1)
                    val = val.strip().strip("'\"").strip()
                    if len(val) >= 6:
                        env_values.add(val)
        except OSError:
            pass

    return env_values, env_files


def generate_preview(
    lines: list[str],
    target_line_1based: int,
    env_values: set[str] | None = None,
    custom_patterns: list[tuple[str, re.Pattern]] | None = None,
) -> str:
    """Generate masked preview for target_line +/- 2 lines."""
    total = len(lines)
    start = max(1, target_line_1based - 2)
    end = min(total, target_line_1based + 2)

    preview_lines = []
    for idx in range(start, end + 1):
        raw_line = lines[idx - 1]
        masked = mask_line(raw_line, env_values, custom_patterns=custom_patterns)
        preview_lines.append(f"{idx:>2}  {masked}")
    return "\n".join(preview_lines)


def scan_text(
    text: str,
    file_display_path: str,
    env_values: set[str] | None = None,
    is_env_file: bool = False,
    custom_patterns: list[tuple[str, re.Pattern]] | None = None,
) -> list[Finding]:
    """Scan string content for secrets and return findings with masked values only."""
    findings: list[Finding] = []
    lines = text.splitlines()
    all_patterns = list(PATTERNS) + (custom_patterns or [])

    for line_idx, line in enumerate(lines, start=1):
        # 1. Standard and custom pattern matching
        for kind, pattern in all_patterns:
            for match in pattern.finditer(line):
                raw_val = match.group(1) if match.lastindex else match.group(0)
                masked = mask_value(kind, raw_val)
                preview = generate_preview(lines, line_idx, env_values, custom_patterns=custom_patterns)
                findings.append(
                    Finding(
                        kind=kind,
                        path=file_display_path,
                        line=line_idx,
                        masked=masked,
                        preview=preview,
                    )
                )

        # 2. .env value matching (only in non-.env files)
        if not is_env_file and env_values:
            for secret_val in sorted(env_values, key=len, reverse=True):
                if secret_val in line:
                    preview = generate_preview(lines, line_idx, env_values, custom_patterns=custom_patterns)
                    findings.append(
                        Finding(
                            kind="env_value",
                            path=file_display_path,
                            line=line_idx,
                            masked=mask_value("env_value", secret_val),
                            preview=preview,
                        )
                    )

    return findings


def scan_folder(folder_path: str | Path, ignore_filter: IgnoreFilter | None = None) -> ScanSummary:
    """Recursively scan a directory or file, filtering out binaries, skipped dirs, large files, and ignored rules."""
    root = Path(folder_path).resolve()
    summary = ScanSummary()

    if not root.exists():
        return summary

    if ignore_filter is None:
        ignore_file = (root if root.is_dir() else root.parent) / ".tscanignore"
        if ignore_file.exists():
            ignore_filter = IgnoreFilter.load(ignore_file)

    env_values, env_files = collect_env_values(root)
    custom_patterns = load_custom_rules(root)

    if root.is_file():
        # Handle scanning a single file directly
        if root.stat().st_size > MAX_FILE_SIZE or is_binary_file(root):
            summary.skipped_files += 1
            return summary
        try:
            with open(root, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            summary.scanned_files += 1
            is_env = root in env_files
            findings = scan_text(
                content,
                root.name,
                env_values,
                is_env_file=is_env,
                custom_patterns=custom_patterns,
            )
            if ignore_filter:
                findings = ignore_filter.filter_findings(findings)
            summary.findings.extend(findings)
        except OSError:
            summary.skipped_files += 1
        return summary

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored directories in place
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]

        for fname in filenames:
            file_path = Path(dirpath) / fname
            try:
                # Size check
                if file_path.stat().st_size > MAX_FILE_SIZE:
                    summary.skipped_files += 1
                    continue
                # Binary check
                if is_binary_file(file_path):
                    summary.skipped_files += 1
                    continue
            except OSError:
                summary.skipped_files += 1
                continue

            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                summary.skipped_files += 1
                continue

            summary.scanned_files += 1
            is_env = file_path.resolve() in env_files
            try:
                display_path = str(file_path.relative_to(root))
            except ValueError:
                display_path = str(file_path)

            findings = scan_text(
                content,
                display_path,
                env_values,
                is_env_file=is_env,
                custom_patterns=custom_patterns,
            )
            if ignore_filter:
                findings = ignore_filter.filter_findings(findings)
            summary.findings.extend(findings)

    return summary
