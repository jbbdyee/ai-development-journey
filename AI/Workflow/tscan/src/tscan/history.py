from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Any
from tscan.config import load_custom_rules
from tscan.git import get_repo_root
from tscan.masker import mask_value
from tscan.patterns import PATTERNS


@dataclass(frozen=True)
class HistoryFinding:
    commit_hash: str
    path: str
    kind: str
    masked: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit_hash": self.commit_hash,
            "path": self.path,
            "kind": self.kind,
            "masked": self.masked,
        }


def scan_history(repo_root: Path | None = None) -> list[HistoryFinding]:
    """Scan past commit history (added '+' lines) using git log -p."""
    root = repo_root or get_repo_root()
    if not root:
        return []

    try:
        res = subprocess.run(
            ["git", "log", "-p", "--no-color", "--diff-filter=AM"],
            cwd=root,
            capture_output=True,
            text=True,
            errors="replace",
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    all_patterns = list(PATTERNS) + load_custom_rules(root)
    findings: list[HistoryFinding] = []

    current_commit = ""
    current_file = ""

    for line in res.stdout.splitlines():
        if line.startswith("commit "):
            parts = line.split()
            if len(parts) >= 2:
                current_commit = parts[1][:8]
        elif line.startswith("diff --git a/"):
            parts = line.split(" b/", 1)
            if len(parts) == 2:
                current_file = parts[1].strip()
        elif line.startswith("+++ "):
            # diff header line, skip
            continue
        elif line.startswith("+"):
            added_text = line[1:]
            for kind, pattern in all_patterns:
                for match in pattern.finditer(added_text):
                    raw = match.group(1) if match.lastindex else match.group(0)
                    masked = mask_value(kind, raw)
                    findings.append(
                        HistoryFinding(
                            commit_hash=current_commit,
                            path=current_file or "unknown",
                            kind=kind,
                            masked=masked,
                        )
                    )

    return findings
