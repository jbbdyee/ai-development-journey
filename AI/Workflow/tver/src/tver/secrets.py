"""Find API-key-like values in a workflow and hide them in every output (R7).

A finding never carries the original value, only a masked form such as
`sk-…(51 chars)`, so it is safe to print, log or put in JSON.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PATTERNS = [
    ("openai-style key", re.compile(r"\bsk-(?:proj-|ant-|live-|test-)?[A-Za-z0-9_\-]{16,}")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("bearer token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{20,}=*")),
    ("private key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
]
# A literal value stored under a name like these is treated as a secret too.
SECRET_NAME = re.compile(r"(?i)(api[_-]?key|apikey|secret|password|passwd|token|authorization|x-api-key)$")
MIN_NAMED_SECRET = 8
NAMED_KIND = "literal secret field"


@dataclass(frozen=True)
class Finding:
    node: str
    path: str
    kind: str
    masked: str

    def describe(self) -> str:
        where = self.node if not self.path else f"{self.node} {self.path}"
        return f"{where}: {self.kind} {self.masked}"


def mask(value: str) -> str:
    """Keep at most the first 3 characters; never enough to reuse."""
    head = value[:3] if len(value) >= 12 else ""
    return f"{head}…({len(value)} chars)"


def _literal(value: Any) -> bool:
    """A typed-in value, not an n8n expression or a credential reference."""
    return (isinstance(value, str) and len(value.strip()) >= MIN_NAMED_SECRET
            and not value.startswith("=") and "{{" not in value)


def scan_text(text: str) -> list[tuple[str, str]]:
    """(kind, matched text) for each pattern hit in a string."""
    hits = []
    for kind, pattern in PATTERNS:
        hits += [(kind, m.group(0)) for m in pattern.finditer(text)]
    return hits


def _walk(value: Any, path: str, sink: list[tuple[str, Any, str | None]]) -> None:
    """Every string leaf with its path and the 'name' of a {name, value} pair it belongs to."""
    if isinstance(value, dict):
        pair_name = value.get("name") if isinstance(value.get("name"), str) and "value" in value else None
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if key == "value" and pair_name is not None and isinstance(item, str):
                sink.append((child, item, pair_name))
            else:
                _walk(item, child, sink)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk(item, f"{path}[{index}]", sink)
    elif isinstance(value, str):
        sink.append((path, value, None))


def find_secrets(workflow: dict) -> list[Finding]:
    found: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    def check(node: str, path: str, value: str, name: str | None) -> None:
        last = name or path.rsplit(".", 1)[-1].split("[", 1)[0]
        hits = scan_text(value)
        if not hits and SECRET_NAME.search(last) and _literal(value):
            hits = [(NAMED_KIND, value)]
        for kind, text in hits:
            if (node, path) not in seen:
                seen.add((node, path))
                found.append(Finding(node, path, kind, mask(text)))

    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        sink: list[tuple[str, Any, str | None]] = []
        _walk({k: v for k, v in node.items() if k != "credentials"}, "", sink)
        for path, value, name in sink:
            check(str(node.get("name", "?")), path, value, name)
    sink = []
    _walk({k: v for k, v in workflow.items() if k not in ("nodes", "connections")}, "", sink)
    for path, value, name in sink:
        check("(workflow)", path, value, name)
    return found


def redact(value: Any, key: str | None = None) -> Any:
    """`value` with secret-looking parts masked; non-strings pass through."""
    if not isinstance(value, str):
        return value
    last = (key or "").rsplit(".", 1)[-1].split("[", 1)[0]
    if key and SECRET_NAME.search(last) and _literal(value) and not scan_text(value):
        return mask(value)
    for _, text in scan_text(value):
        value = value.replace(text, mask(text))
    return value
