"""Write one JSON record per run with sensitive values removed."""

import json
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tcrew.core import RunResult


EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
PHONE = re.compile(
    r"(?<![A-Za-z0-9])(?:\+82[-.\s]?(?:0)?|0)"
    r"(?:10|11|16|17|18|19|2|3[1-3]|4[1-4]|5[1-5]|6[1-4])"
    r"[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)"
)
RESIDENT_ID = re.compile(r"(?<!\d)\d{6}[-\s]?[1-8]\d{6}(?!\d)")


def redact(value: str) -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        value = value.replace(key, "[REDACTED]")
    value = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(api[_-]?key\s*[:=]\s*)\S+", r"\1[REDACTED]", value)
    return value


def redact_record(value: str) -> str:
    """Mask common personal identifiers in persisted text only."""
    value = redact(value)
    value = EMAIL.sub("[EMAIL_REDACTED]", value)
    value = PHONE.sub("[PHONE_REDACTED]", value)
    return RESIDENT_ID.sub("[ID_REDACTED]", value)


def save_record(result: RunResult, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    path = directory / f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid4().hex}.json"
    payload = {
        "started_at": timestamp.isoformat(),
        "status": result.status,
        "reason": result.reason,
        "revisions": result.revisions,
        "roles": [asdict(item) for item in result.results],
    }
    for item in payload["roles"]:
        item["input"] = redact_record(item["input"])
        item["output"] = redact_record(item["output"])
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
