from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from tscan.models import Finding


@dataclass
class IgnoreRule:
    rule_type: str  # "path_line", "kind_path", "glob"
    pattern: str
    line: int | None = None
    kind: str | None = None


class IgnoreFilter:
    def __init__(self, rules: list[IgnoreRule] | None = None) -> None:
        self.rules = rules or []

    @classmethod
    def load(cls, ignore_file_path: Path) -> IgnoreFilter:
        rules: list[IgnoreRule] = []
        if not ignore_file_path.exists() or not ignore_file_path.is_file():
            return cls(rules)

        try:
            with open(ignore_file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    rules.append(cls.parse_rule(line))
        except OSError:
            pass

        return cls(rules)

    @staticmethod
    def parse_rule(line: str) -> IgnoreRule:
        # Check path:line (e.g. "a.txt:12") vs kind:path (e.g. "phone:contact.md")
        if ":" in line:
            parts = line.split(":", 1)
            # If the second part is numeric, it is path:line
            if parts[1].strip().isdigit():
                return IgnoreRule(
                    rule_type="path_line",
                    pattern=parts[0].strip(),
                    line=int(parts[1].strip()),
                )
            else:
                # kind:path
                return IgnoreRule(
                    rule_type="kind_path",
                    pattern=parts[1].strip(),
                    kind=parts[0].strip(),
                )
        return IgnoreRule(rule_type="glob", pattern=line.strip())

    def is_ignored(self, finding: Finding) -> bool:
        normalized_path = finding.path.replace("\\", "/").lstrip("./")
        file_name = Path(normalized_path).name

        for rule in self.rules:
            rule_pattern = rule.pattern.replace("\\", "/").lstrip("./")

            if rule.rule_type == "path_line":
                if (
                    normalized_path == rule_pattern
                    or normalized_path.endswith("/" + rule_pattern)
                    or file_name == rule_pattern
                ) and finding.line == rule.line:
                    return True

            elif rule.rule_type == "kind_path":
                if finding.kind == rule.kind:
                    if (
                        normalized_path == rule_pattern
                        or normalized_path.endswith("/" + rule_pattern)
                        or fnmatch(normalized_path, rule_pattern)
                        or fnmatch(file_name, rule_pattern)
                    ):
                        return True

            elif rule.rule_type == "glob":
                if (
                    normalized_path == rule_pattern
                    or fnmatch(normalized_path, rule_pattern)
                    or fnmatch(file_name, rule_pattern)
                ):
                    return True
                # Match directory glob like "docs/*" or "docs/"
                clean_dir = rule_pattern.rstrip("/*")
                if normalized_path.startswith(clean_dir + "/"):
                    return True

        return False

    def filter_findings(self, findings: list[Finding]) -> list[Finding]:
        return [f for f in findings if not self.is_ignored(f)]

    @staticmethod
    def append_rule(ignore_file_path: Path, rule_str: str) -> None:
        try:
            with open(ignore_file_path, "a", encoding="utf-8") as f:
                f.write(f"{rule_str}\n")
        except OSError:
            pass
