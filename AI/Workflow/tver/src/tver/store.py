"""Version store: a separate git repository of cleaned workflow JSON (R5 · R6).

One workflow per file, `<name>.json`. Each save is one commit whose subject
is the change summary against the previous saved version.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import engine, secrets
from .engine import Change

DEFAULT_REPO = Path("~/.tver/store")
MARKER = "tver-store"  # inside .git/, so the store's history holds only workflow versions
FALLBACK_IDENTITY = {"user.name": "tver", "user.email": "tver@localhost"}
# Never let an outer git context (hooks, worktrees) redirect commands to another repository.
OUTER_GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                 "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES")


class StoreError(RuntimeError):
    """The store or a version in it cannot be used."""


class SecretsFound(StoreError):
    """Refused to save: the workflow holds API-key-like values (R7). Never carries the values."""

    def __init__(self, where: str, findings: list[secrets.Finding]):
        self.findings = findings
        shown = "; ".join(f.describe() for f in findings[:5])
        more = f" (+{len(findings) - 5} more)" if len(findings) > 5 else ""
        super().__init__(f"{where}: refused, {len(findings)} secret-looking value(s): {shown}{more}. "
                         "Move them into n8n credentials and save again.")


def resolve_repo(explicit: str | os.PathLike | None = None) -> Path:
    """`--repo` beats `TVER_REPO` beats `~/.tver/store`."""
    chosen = explicit or os.environ.get("TVER_REPO") or DEFAULT_REPO
    return Path(chosen).expanduser().resolve()


def safe_name(text: str) -> str:
    """Lower-case file-safe name: spaces, slashes and symbols become `-`; letters (Korean too) stay."""
    text = unicodedata.normalize("NFC", text).strip().lower()
    if text.endswith(".json"):
        text = text[:-5]
    text = re.sub(r"[^\w.]+", "-", text).strip("-._")
    return text or "workflow"


@dataclass
class Version:
    rev: str
    time: str
    author: str
    subject: str

    @property
    def summary(self) -> str:
        """Subject without the leading `<name>: `."""
        return self.subject.split(": ", 1)[-1]


@dataclass
class SaveResult:
    name: str
    saved: bool
    rev: str  # new commit, or the matching latest one when nothing changed
    changes: list[Change] = field(default_factory=list)
    first: bool = False
    message: str = ""


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)

    # ------------------------------------------------------------ git
    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k not in OUTER_GIT_ENV}
        try:
            result = subprocess.run(
                ["git", "-c", "core.quotepath=false", "-c", "commit.gpgsign=false", *self._identity(), *args],
                cwd=self.path, env=env, capture_output=True, text=True, encoding="utf-8",
            )
        except FileNotFoundError:
            raise StoreError("git is not installed") from None
        if check and result.returncode != 0:
            raise StoreError(f"git {args[0]} failed: {result.stderr.strip() or result.stdout.strip()}")
        return result

    def _identity(self) -> list[str]:
        """The user's own git name/email when configured, so the log says who saved."""
        if not hasattr(self, "_identity_args"):
            self._identity_args = []
            for key, fallback in FALLBACK_IDENTITY.items():
                found = subprocess.run(["git", "config", "--global", "--get", key],
                                       capture_output=True, text=True, check=False)
                if not found.stdout.strip():
                    self._identity_args += ["-c", f"{key}={fallback}"]
        return self._identity_args

    def exists(self) -> bool:
        return (self.path / ".git" / MARKER).is_file()

    def ensure(self) -> None:
        """Create the store on first use. Never adopt a folder that is not a tver store."""
        if self.exists():
            return
        if self.path.exists() and any(self.path.iterdir()):
            raise StoreError(f"{self.path} exists and is not a tver store (no .git/{MARKER}); "
                             "choose an empty folder with --repo")
        self.path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")
        (self.path / ".git" / MARKER).write_text("tver version store; files are cleaned n8n workflows\n",
                                                 encoding="utf-8")

    def require(self) -> None:
        if not self.exists():
            raise StoreError(f"no tver store at {self.path} (save a workflow first)")

    # ------------------------------------------------------------ versions
    @staticmethod
    def filename(name: str) -> str:
        return f"{safe_name(name)}.json"

    def versions(self, name: str) -> list[Version]:
        """Saved versions of one workflow, newest first."""
        self.require()
        if self.git("rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode != 0:
            return []  # no commits yet
        out = self.git("log", "--format=%h%x1f%ad%x1f%an%x1f%s", "--date=format-local:%Y-%m-%d %H:%M:%S",
                       "--", self.filename(name)).stdout
        return [Version(*line.split("\x1f", 3)) for line in out.splitlines() if line]

    def names(self) -> list[str]:
        self.require()
        files = self.git("ls-files", "-z", "--", "*.json").stdout.split("\0")
        return sorted(f[:-5] for f in files if f.endswith(".json") and "/" not in f)

    def read(self, rev: str, name: str) -> dict:
        """Cleaned workflow as stored in `rev`."""
        self.require()
        path = self.filename(name)
        if not self.versions(name):
            raise StoreError(f"no saved versions of '{safe_name(name)}'")
        shown = self.git("show", f"{rev}:{path}", check=False)
        if shown.returncode != 0:
            raise StoreError(f"'{safe_name(name)}' has no version at revision '{rev}'")
        try:
            data = json.loads(shown.stdout)
        except json.JSONDecodeError:
            raise StoreError(f"{path} at {rev} is not valid JSON") from None
        engine.validate(data, f"{path}@{rev}")
        return data

    def latest(self, name: str) -> dict | None:
        found = self.versions(name)
        return self.read(found[0].rev, name) if found else None

    def resolve_rev(self, rev: str) -> str:
        found = self.git("rev-parse", "--verify", "--quiet", "--short", f"{rev}^{{commit}}", check=False)
        if found.returncode != 0:
            raise StoreError(f"unknown revision '{rev}'")
        return found.stdout.strip()

    # ------------------------------------------------------------ save
    def save(self, workflow: dict, name: str) -> SaveResult:
        """Commit the cleaned workflow unless it means the same as the latest version.

        A workflow with secret-looking values is refused before anything is written.
        """
        name = safe_name(name)
        engine.validate(workflow, name)
        found = secrets.find_secrets(workflow)
        if found:
            raise SecretsFound(name, found)
        self.ensure()
        cleaned = engine.clean(workflow)
        previous = self.latest(name)
        if previous is not None:
            changes = engine.compare(previous, cleaned)
            if not changes:
                return SaveResult(name, False, self.versions(name)[0].rev)
            message = commit_message(name, changes)
        else:
            changes = []
            message = f"{name}: first version · {len(cleaned['nodes'])} node(s)"
        path = self.path / self.filename(name)
        path.write_text(engine.dumps(cleaned), encoding="utf-8")
        self.git("add", "--", path.name)
        self.git("commit", "-q", "-m", message, "--", path.name)
        return SaveResult(name, True, self.versions(name)[0].rev, changes, previous is None, message)


def commit_message(name: str, changes: list[Change]) -> str:
    lines = [f"{name}: {engine.summary(changes)}", ""]
    lines += [describe(change) for change in changes]
    return "\n".join(lines) + "\n"


def describe(change: Change) -> str:
    """One plain line per change, used in commit bodies."""
    if change.op == engine.NODE_ADDED:
        return f"+ node {change.node} [{change.category}]"
    if change.op == engine.NODE_REMOVED:
        return f"- node {change.node} [{change.category}]"
    if change.op == engine.RENAMED:
        return f"> renamed {change.before} -> {change.after} [{change.category}]"
    if change.op == engine.LINK_ADDED:
        return f"+ link {change.after} [{change.category}]"
    if change.op == engine.LINK_REMOVED:
        return f"- link {change.before} [{change.category}]"
    return f"~ {change.node} {change.key} [{change.category}]"


# ---------------------------------------------------------------- folder save (R13)
@dataclass
class Entry:
    file: str
    status: str  # saved · unchanged · skipped · refused · error
    detail: str
    name: str | None = None
    rev: str | None = None


def is_workflow(data: object) -> bool:
    return isinstance(data, dict) and isinstance(data.get("nodes"), list) and isinstance(data.get("connections"), dict)


def save_folder(store: Store, folder: Path) -> list[Entry]:
    """Save every top-level `*.json` that is a workflow; everything else is `skipped`."""
    entries: list[Entry] = []
    used: dict[str, str] = {}
    for path in sorted(p for p in Path(folder).iterdir() if p.is_file() and not p.name.startswith(".")):
        if path.suffix.lower() != ".json":
            entries.append(Entry(path.name, "skipped", "not a .json file"))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            entries.append(Entry(path.name, "skipped", "not valid JSON"))
            continue
        if not is_workflow(data):
            entries.append(Entry(path.name, "skipped", "not an n8n workflow (no nodes/connections)"))
            continue
        name = safe_name(path.name)
        if name in used:
            entries.append(Entry(path.name, "error", f"name '{name}' already used by {used[name]}", name))
            continue
        used[name] = path.name
        entries.append(save_entry(store, data, name, path.name))
    return entries


def save_entry(store: Store, workflow: dict, name: str, label: str) -> Entry:
    try:
        result = store.save(workflow, name)
    except SecretsFound as exc:
        return Entry(label, "refused", str(exc), name)
    except (StoreError, engine.WorkflowError) as exc:
        return Entry(label, "error", str(exc), name)
    if not result.saved:
        return Entry(label, "unchanged", f"matches {result.rev}", result.name, result.rev)
    detail = (f"first version · {len(engine.clean(workflow)['nodes'])} node(s)" if result.first
              else engine.summary(result.changes))
    return Entry(label, "saved", detail, result.name, result.rev)


def tally(entries: list[Entry]) -> dict[str, int]:
    out = {status: 0 for status in ("saved", "unchanged", "skipped", "refused", "error")}
    for entry in entries:
        out[entry.status] += 1
    return out


# ---------------------------------------------------------------- restore (R10)
def with_layout(cleaned: dict) -> dict:
    """Give nodes simple positions again so the file imports cleanly into n8n.

    Columns follow the main links from the trigger(s); positions are ignored by
    every comparison, so the restored file still equals the stored version.
    """
    found = engine.links(cleaned)
    main = [l for l in found if l.output == "main"]
    serves = {l.source: l.target for l in found if l.output != "main"}  # model/tool → node it serves
    has_input = {l.target for l in main}
    column = {n["name"]: 0 for n in cleaned["nodes"] if n["name"] not in has_input and n["name"] not in serves}
    queue = list(column)
    while queue:
        current = queue.pop(0)
        for link in main:
            if link.source == current and link.target not in column:
                column[link.target] = column[current] + 1
                queue.append(link.target)
    rows: dict[int, int] = {}
    nodes = []
    for node in cleaned["nodes"]:
        name = node["name"]
        sub = name in serves and name not in column
        col = column.get(serves.get(name, ""), 0) if sub else column.get(name, 0)
        row = rows.get(col, 0)
        rows[col] = row + 1
        nodes.append({**node, "position": [col * 240, 300 + row * 200 + (100 if sub else 0)]})
    return {**cleaned, "nodes": nodes}


def restore(store: Store, rev: str, name: str, output: Path | None, force: bool = False) -> str:
    """Write version `rev` of `name` to `output` (or return it when output is None). Never commits."""
    text = json.dumps(with_layout(store.read(rev, name)), ensure_ascii=False, indent=2) + "\n"
    if output is not None:
        if output.exists() and not force:
            raise StoreError(f"{output} already exists (use --force to overwrite)")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    return text
