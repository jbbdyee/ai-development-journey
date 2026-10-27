"""Local profiles, individual records, and saved-run history."""

from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from .engine import Sample, save_result


PROFILE_NAME = re.compile(r"[A-Za-z0-9_-]+\Z")


def data_dir() -> Path:
    return Path.home() / ".tbench"


def log_sample(path: Path, sample: Sample) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {key: value for key, value in asdict(sample).items()
              if key in ("timestamp", "number", "status", "seconds", "error_kind")}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def profile_path() -> Path:
    return data_dir() / "profiles.json"


def load_profiles() -> dict:
    path = profile_path()
    if not path.exists():
        return {}
    content = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict):
        raise ValueError("profiles file must contain an object")
    return content


def save_profile(name: str, profile: dict) -> Path:
    if not PROFILE_NAME.fullmatch(name):
        raise ValueError("profile name must use letters, digits, underscore, or hyphen")
    url = urlsplit(profile["url"])
    if url.scheme not in ("http", "https") or not url.hostname:
        raise ValueError("profile URL must be http or https")
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("profile URL cannot contain user info, query, or fragment; supply secrets at run time")
    profiles = load_profiles()
    profiles[name] = profile
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profiles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def save_default_result(result: dict) -> Path:
    stamp = datetime.fromisoformat(result["started_at"]).strftime("%Y%m%dT%H%M%S%f")
    path = data_dir() / "runs" / f"{stamp}-{uuid.uuid4().hex[:8]}.json"
    save_result(result, path)
    return path


def history(include_paths: bool = False) -> list[dict]:
    rows = []
    for path in (data_dir() / "runs").glob("*.json"):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
            summary = result["summary"]
            row = {
                "started_at": result["started_at"], "url": result["url"],
                "count": result["count"], "p50": summary["p50"],
                "p95": summary["p95"], "failures": summary["failures"],
            }
            datetime.fromisoformat(row["started_at"])
            if (not isinstance(row["url"], str)
                    or not isinstance(row["count"], int) or isinstance(row["count"], bool)
                    or not isinstance(row["failures"], int) or isinstance(row["failures"], bool)
                    or any(value is not None and (
                        isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value)
                    ) for value in (row["p50"], row["p95"]))):
                continue
            if include_paths:
                row["path"] = path
            rows.append(row)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(rows, key=lambda row: row["started_at"], reverse=True)
