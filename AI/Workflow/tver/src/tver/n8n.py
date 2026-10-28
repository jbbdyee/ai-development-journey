"""Read workflows out of a running n8n, read-only (R9).

The only command sent to n8n is `n8n export:workflow --all`, which prints the
workflows to stdout. Nothing is imported, updated, activated or deleted, and
no file is written inside the container.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .store import Entry, Store, safe_name, save_entry

EXPORT = ("n8n", "export:workflow", "--all")


class N8nError(RuntimeError):
    pass


def find_container(explicit: str | None = None) -> str:
    """--container, else $TVER_N8N_CONTAINER, else the running container of compose service `n8n`."""
    if explicit or os.environ.get("TVER_N8N_CONTAINER"):
        return explicit or os.environ["TVER_N8N_CONTAINER"]
    if not shutil.which("docker"):
        raise N8nError("docker is not installed; use --container or --file")
    found = subprocess.run(["docker", "ps", "--filter", "label=com.docker.compose.service=n8n",
                            "--format", "{{.Names}}"], capture_output=True, text=True, check=False)
    names = found.stdout.split()
    if len(names) != 1:
        raise N8nError("cannot pick an n8n container" + (f" ({', '.join(names)})" if names else " (none running)")
                       + "; use --container NAME")
    return names[0]


def export_from_container(container: str) -> list[dict]:
    try:
        result = subprocess.run(["docker", "exec", container, *EXPORT],
                                capture_output=True, text=True, encoding="utf-8", check=False, timeout=180)
    except FileNotFoundError:
        raise N8nError("docker is not installed") from None
    except subprocess.TimeoutExpired:
        raise N8nError(f"n8n export in '{container}' timed out") from None
    if result.returncode != 0:
        raise N8nError(f"n8n export in '{container}' failed: {(result.stderr or result.stdout).strip()[:300]}")
    return parse_export(result.stdout, f"container '{container}'")


def export_from_file(path: Path) -> list[dict]:
    try:
        return parse_export(Path(path).read_text(encoding="utf-8"), str(path))
    except OSError as exc:
        raise N8nError(f"{path}: cannot read ({exc.strerror})") from None


def parse_export(text: str, where: str) -> list[dict]:
    """JSON from the export output; log lines n8n may print before it are ignored."""
    if not text.strip():
        return []
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.lstrip()[:1] in ("[", "{"):
            try:
                data = json.loads("".join(lines[index:]))
            except json.JSONDecodeError:
                continue
            workflows = data if isinstance(data, list) else [data]
            return [w for w in workflows if isinstance(w, dict)]
    raise N8nError(f"{where}: export output is not JSON")


def store_names(workflows: list[dict]) -> list[str]:
    """Safe file names; workflows sharing a name get their n8n id appended (stable across pulls),
    or a running number when they have no id."""
    base = [safe_name(str(w.get("name") or "workflow")) for w in workflows]
    out: list[str] = []
    seen: dict[str, int] = {}
    for name, workflow in zip(base, workflows):
        if base.count(name) > 1:
            seen[name] = seen.get(name, 0) + 1
            suffix = safe_name(str(workflow.get("id"))) if workflow.get("id") else str(seen[name])
            name = f"{name}-{suffix}"
        candidate, number = name, 2
        while candidate in out:  # same id twice: keep them apart
            candidate, number = f"{name}-{number}", number + 1
        out.append(candidate)
    return out


def pull(store: Store, workflows: list[dict], include_archived: bool = False) -> list[Entry]:
    entries: list[Entry] = []
    for workflow, name in zip(workflows, store_names(workflows)):
        label = str(workflow.get("name") or name)
        if workflow.get("isArchived") and not include_archived:
            entries.append(Entry(label, "skipped", "archived in n8n", name))
            continue
        entries.append(save_entry(store, workflow, name, label))
    return entries
