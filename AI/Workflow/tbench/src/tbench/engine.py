"""HTTP measurement and statistics independent of the UI."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx


SECRET_HEADER_PARTS = ("authorization", "api-key", "apikey", "token", "secret", "cookie")


@dataclass
class Sample:
    number: int
    timestamp: str
    status: int | None
    seconds: float
    error_kind: str | None = None
    timings: dict[str, float] | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: "***" if any(part in key.lower() for part in SECRET_HEADER_PARTS) else value
        for key, value in headers.items()
    }


def body_hash(body: bytes | None) -> str | None:
    return hashlib.sha256(body).hexdigest() if body is not None else None


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def summarize(samples: list[Sample]) -> dict:
    successful = [s.seconds for s in samples if s.error_kind is None]
    excluding_first = [s.seconds for s in samples if s.number != 1 and s.error_kind is None]
    failures = Counter(s.error_kind for s in samples if s.error_kind)
    timing_values: dict[str, list[float]] = {}
    for sample in samples:
        if sample.error_kind is None and sample.timings:
            for key, value in sample.timings.items():
                timing_values.setdefault(key, []).append(value)
    return {
        "count": len(samples),
        "successes": len(successful),
        "failures": sum(failures.values()),
        "failure_kinds": dict(failures),
        "p50": percentile(successful, 0.5),
        "p95": percentile(successful, 0.95),
        "max": max(successful) if successful else None,
        "p50_without_first": percentile(excluding_first, 0.5),
        "timings_ms": {key: sum(values) / len(values) for key, values in timing_values.items()},
    }


def passes_limits(summary: dict, max_p95: float | None, max_failures: int | None) -> bool | None:
    if max_p95 is None and max_failures is None:
        return None
    if summary["successes"] == 0:
        return False
    return (
        (max_p95 is None or summary["p95"] <= max_p95)
        and (max_failures is None or summary["failures"] <= max_failures)
    )


def extract_timings(response: httpx.Response) -> dict[str, float] | None:
    try:
        payload = response.json()
    except (ValueError, UnicodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("timings"), dict):
        return None
    return {
        key: float(value)
        for key, value in payload["timings"].items()
        if key.endswith("_ms") and isinstance(value, (int, float))
        and not isinstance(value, bool) and math.isfinite(value)
    } or None


def request_once(client: httpx.Client, url: str, body: bytes | None, headers: dict[str, str], number: int) -> Sample:
    started = time.perf_counter()
    stamp = utc_now()
    try:
        response = client.request("POST" if body is not None else "GET", url, content=body, headers=headers)
        elapsed = time.perf_counter() - started
        status = response.status_code
        kind = "http_5xx" if status >= 500 else "http_4xx" if status >= 400 else None
        return Sample(number, stamp, status, elapsed, kind, extract_timings(response))
    except httpx.TimeoutException:
        return Sample(number, stamp, None, time.perf_counter() - started, "timeout")
    except httpx.ConnectError:
        return Sample(number, stamp, None, time.perf_counter() - started, "connect")
    except httpx.RequestError:
        return Sample(number, stamp, None, time.perf_counter() - started, "request")


def run(
    url: str,
    body: bytes | None,
    headers: dict[str, str],
    count: int,
    timeout: float = 30,
    warmup: int = 0,
    on_sample: Callable[[Sample, dict], None] | None = None,
    concurrency: int = 1,
) -> dict:
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    samples: list[Sample] = []
    started_at = utc_now()
    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
        for _ in range(warmup):
            request_once(client, url, body, headers, 0)
        if concurrency == 1:
            completed = (request_once(client, url, body, headers, number) for number in range(1, count + 1))
            for sample in completed:
                samples.append(sample)
                if on_sample:
                    on_sample(sample, summarize(samples))
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(request_once, client, url, body, headers, number) for number in range(1, count + 1)]
                for future in as_completed(futures):
                    sample = future.result()
                    samples.append(sample)
                    if on_sample:
                        on_sample(sample, summarize(samples))
    return {
        "schema_version": 1,
        "started_at": started_at,
        "url": url,
        "method": "POST" if body is not None else "GET",
        "body_sha256": body_hash(body),
        "count": count,
        "concurrency": concurrency,
        "warmup": warmup,
        "timeout": timeout,
        "headers": redact_headers(headers),
        "samples": [asdict(sample) for sample in samples],
        "summary": summarize(samples),
    }


def save_result(result: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compare(before: dict, after: dict) -> dict:
    differences = []
    for key, label in (("url", "URL"), ("body_sha256", "body hash"), ("count", "N")):
        if before.get(key) != after.get(key):
            differences.append(label)
    metrics = {}
    for key in ("p50", "p95", "max", "failures"):
        old = before["summary"].get(key)
        new = after["summary"].get(key)
        percent = None if old in (None, 0) or new is None else (new - old) / old * 100
        metrics[key] = {"before": old, "after": new, "change_percent": percent}
    return {"warnings": differences, "metrics": metrics}
