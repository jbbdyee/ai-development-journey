from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    line: int
    masked: str
    preview: str = ""


@dataclass
class ScanSummary:
    scanned_files: int = 0
    skipped_files: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def findings_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.kind] = counts.get(f.kind, 0) + 1
        return counts

    @property
    def findings_by_file(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.path] = counts.get(f.path, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_files": self.scanned_files,
            "skipped_files": self.skipped_files,
            "total_findings": len(self.findings),
            "by_kind": self.findings_by_kind,
            "by_file": self.findings_by_file,
            "findings": [
                {
                    "kind": f.kind,
                    "path": f.path,
                    "line": f.line,
                    "masked": f.masked,
                }
                for f in self.findings
            ],
        }
