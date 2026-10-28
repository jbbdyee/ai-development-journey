"""Clean and compare n8n workflows. No terminal or git code lives here.

CLI, TUI and tests all call `load_workflow` / `clean` / `compare` / `summary`
so they see exactly the same list of changes.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import secrets

# Export metadata and screen layout: never a meaningful change (R2).
WORKFLOW_META = {
    "id", "versionId", "updatedAt", "createdAt", "meta", "pinData", "tags",
    "active", "staticData", "triggerCount", "shared", "isArchived", "activeVersionId",
    "versionCounter", "versionMetadata", "sourceWorkflowId", "nodeGroups", "homeProject",
    "parentFolder", "scopes", "usedCredentials",
}
NODE_META = {"id", "position", "webhookId"}

LONG_TEXT = 80  # longer than this, or multi-line → line diff (R3)
CATEGORIES = ("model", "prompt", "flow")

# Change.op values
NODE_ADDED = "node_added"
NODE_REMOVED = "node_removed"
CHANGED = "changed"
LINK_ADDED = "link_added"
LINK_REMOVED = "link_removed"
RENAMED = "renamed"
WORKFLOW = "(workflow)"  # pseudo node for top-level settings


class WorkflowError(ValueError):
    """The input is not a readable n8n workflow."""


@dataclass(frozen=True)
class Link:
    source: str
    output: str
    output_index: int
    target: str
    input: str
    input_index: int

    def label(self) -> str:
        src = self.source if self.output_index == 0 else f"{self.source}[{self.output_index}]"
        dst = self.target if self.input_index == 0 else f"{self.target}[{self.input_index}]"
        kind = self.output if self.output == self.input else f"{self.output}→{self.input}"
        return f"{src} → {dst} ({kind})"


@dataclass
class Change:
    op: str
    node: str
    category: str
    key: str | None = None
    before: Any = None
    after: Any = None
    lines: list[str] = field(default_factory=list)
    note: str = ""


# ---------------------------------------------------------------- load & clean
def load_workflow(path: str | Path) -> dict:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise WorkflowError(f"{path}: file not found") from None
    except OSError as exc:
        raise WorkflowError(f"{path}: cannot read ({exc.strerror})") from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"{path}: invalid JSON (line {exc.lineno})") from None
    validate(data, str(path))
    return data


def validate(data: Any, where: str = "workflow") -> None:
    if not isinstance(data, dict):
        raise WorkflowError(f"{where}: top level must be an object")
    if not isinstance(data.get("nodes"), list) or not isinstance(data.get("connections"), dict):
        raise WorkflowError(f"{where}: not an n8n workflow (needs 'nodes' list and 'connections' object)")
    seen: set[str] = set()
    for index, node in enumerate(data["nodes"]):
        if not isinstance(node, dict) or not isinstance(node.get("name"), str):
            raise WorkflowError(f"{where}: nodes[{index}] has no name")
        if node["name"] in seen:
            raise WorkflowError(f"{where}: duplicate node name '{node['name']}'")
        seen.add(node["name"])


def _sorted(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sorted(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted(item) for item in value]
    return value


def links(workflow: dict) -> list[Link]:
    found: set[Link] = set()
    for source, outputs in (workflow.get("connections") or {}).items():
        for output, slots in (outputs or {}).items():
            for out_index, targets in enumerate(slots or []):
                for target in targets or []:
                    if not isinstance(target, dict) or not isinstance(target.get("node"), str):
                        raise WorkflowError(f"connection from '{source}' has no target node")
                    found.add(Link(source, output, out_index, target["node"],
                                   target.get("type", output), int(target.get("index", 0))))
    return sorted(found, key=vars_key)


def clean(workflow: dict) -> dict:
    """Drop metadata, sort nodes by name and keys alphabetically, flatten links.

    The result is what gets compared and what gets stored, so a stored
    version never carries ids or positions back into the next comparison.
    """
    validate(workflow)
    nodes = [
        _sorted({k: v for k, v in node.items() if k not in NODE_META})
        for node in sorted(workflow["nodes"], key=lambda n: n["name"])
    ]
    out = {k: _sorted(v) for k, v in workflow.items()
           if k not in WORKFLOW_META and k not in ("nodes", "connections") and v is not None}
    out["nodes"] = nodes
    out["connections"] = _connections(links(workflow))
    return dict(sorted(out.items()))


def _connections(found: list[Link]) -> dict:
    """n8n-shaped connections rebuilt from links: sorted, no duplicates."""
    out: dict = {}
    for link in found:
        slots = out.setdefault(link.source, {}).setdefault(link.output, [])
        while len(slots) <= link.output_index:
            slots.append([])
        slots[link.output_index].append({"index": link.input_index, "node": link.target, "type": link.input})
    return _sorted(out)


def dumps(cleaned: dict) -> str:
    """Stable text form of a cleaned workflow (fixed key order, UTF-8)."""
    return json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------- compare
def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """Leaf values by dotted path; list items as `key[0]`. Empty containers have no leaves."""
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            out.update(flatten(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.update(flatten(item, f"{prefix}[{index}]"))
    else:
        out[prefix] = value
    return out


def category(node: dict | None, key: str | None) -> str:
    """model / prompt / flow, fixed rules from SPEC §3."""
    if node is None or key is None:
        return "flow"
    kind = str(node.get("type", "")).lower()
    short = kind.rsplit(".", 1)[-1]
    if short.startswith("lmchat") and (key == "parameters.model" or key.startswith("parameters.model.")):
        return "model"
    if short == "agent" and key in ("parameters.text", "parameters.options.systemMessage"):
        return "prompt"
    if short == "code" and key == "parameters.jsCode":
        return "prompt"
    return "flow"


def is_long(value: Any) -> bool:
    return isinstance(value, str) and (len(value) > LONG_TEXT or "\n" in value)


def line_diff(before: Any, after: Any, context: int = 1) -> list[str]:
    """`+ ` / `- ` / `  ` prefixed lines; hunks separated by `…`."""
    a = before.splitlines() if isinstance(before, str) else []
    b = after.splitlines() if isinstance(after, str) else []
    out: list[str] = []
    for group in difflib.SequenceMatcher(None, a, b, autojunk=False).get_grouped_opcodes(context):
        if out:
            out.append("…")
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                out.extend(f"  {line}" for line in a[i1:i2])
                continue
            out.extend(f"- {line}" for line in a[i1:i2])
            out.extend(f"+ {line}" for line in b[j1:j2])
    return out


def _setting_changes(name: str, old: dict | None, new: dict | None) -> list[Change]:
    a = flatten(old or {})
    b = flatten(new or {})
    a.pop("name", None)
    b.pop("name", None)
    owner = new if new is not None else old
    changes = []
    for key in sorted(set(a) | set(b)):
        before, after = a.get(key), b.get(key)
        if key in a and key in b and before == after:
            continue
        change = Change(CHANGED, name, category(owner, key), key, before, after)
        if is_long(before) or is_long(after):
            change.lines = line_diff(before, after)
        changes.append(change)
    return changes


def _without_name(node: dict) -> dict:
    return {k: v for k, v in node.items() if k != "name"}


def _reference_forms(name: str) -> list[str]:
    """Expression forms that point at a node by name: $('X'), $("X"), $node['X'], $node["X"], $items('X')."""
    forms = []
    for quote in ("'", '"'):
        forms += [f"$({quote}{name}{quote})", f"$node[{quote}{name}{quote}]", f"$items({quote}{name}{quote}"]
    return forms


def _rename_references(value: Any, old: str, new: str) -> Any:
    if isinstance(value, dict):
        return {k: _rename_references(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [_rename_references(v, old, new) for v in value]
    if isinstance(value, str):
        for form in _reference_forms(old):
            value = value.replace(form, form.replace(old, new, 1))
    return value


def find_renames(old: dict, new: dict) -> dict[str, str]:
    """old name → new name for unmatched nodes identical except for their name (R12).

    References to the old name in other nodes' expressions are rewritten first,
    as n8n itself does on rename, so the pair compares equal.
    """
    old_names = {n["name"] for n in old["nodes"]}
    new_names = {n["name"] for n in new["nodes"]}
    gone = sorted(old_names - new_names)
    added = sorted(new_names - old_names)
    renames: dict[str, str] = {}
    for old_name in gone:
        before = next(n for n in old["nodes"] if n["name"] == old_name)
        for new_name in added:
            if new_name in renames.values():
                continue
            after = next(n for n in new["nodes"] if n["name"] == new_name)
            if _without_name(_rename_references(before, old_name, new_name)) == _without_name(after):
                renames[old_name] = new_name
                break
    return renames


def _apply_renames(workflow: dict, renames: dict[str, str]) -> dict:
    """`workflow` as if its nodes already had the new names (nodes, references, links)."""
    nodes = []
    for node in workflow["nodes"]:
        for old_name, new_name in renames.items():
            node = _rename_references(node, old_name, new_name)
        if node["name"] in renames:
            node = {**node, "name": renames[node["name"]]}
        nodes.append(node)
    found = [Link(renames.get(l.source, l.source), l.output, l.output_index,
                  renames.get(l.target, l.target), l.input, l.input_index) for l in links(workflow)]
    return clean({**workflow, "nodes": nodes, "connections": _connections(sorted(set(found), key=vars_key))})


def vars_key(link: Link) -> tuple:
    return (link.source, link.output, link.output_index, link.target, link.input, link.input_index)


def _redact(changes: list[Change], old: dict, new: dict) -> list[Change]:
    """Mask API-key-like values so no output shows them (R7)."""
    # whole value hidden only where the field name marks it secret; pattern hits are masked in place
    secret_paths = {(f.node, f.path) for wf in (old, new) for f in secrets.find_secrets(wf)
                    if f.kind == secrets.NAMED_KIND}
    for change in changes:
        hidden = (change.node, change.key) in secret_paths
        for attr in ("before", "after"):
            value = getattr(change, attr)
            if hidden and isinstance(value, str):
                setattr(change, attr, secrets.mask(value))
            else:
                setattr(change, attr, secrets.redact(value, change.key))
        if hidden:
            change.lines = [line[:2] + secrets.mask(line[2:]) if line[:2] in ("+ ", "- ") else line
                            for line in change.lines]
        else:
            change.lines = [secrets.redact(line) for line in change.lines]
    return changes


def compare(old: dict, new: dict) -> list[Change]:
    """Semantic changes from `old` to `new` (raw or cleaned workflows)."""
    old, new = clean(old), clean(new)
    changes: list[Change] = []
    renames = find_renames(old, new)
    for old_name, new_name in renames.items():
        changes.append(Change(RENAMED, new_name, "flow", None, old_name, new_name))
    original = {n["name"]: flatten(n) for n in old["nodes"]}
    if renames:
        old = _apply_renames(old, renames)
    old_nodes = {n["name"]: n for n in old["nodes"]}
    new_nodes = {n["name"]: n for n in new["nodes"]}

    top_old = {k: v for k, v in old.items() if k not in ("nodes", "connections", "name")}
    top_new = {k: v for k, v in new.items() if k not in ("nodes", "connections", "name")}
    changes += _setting_changes(WORKFLOW, top_old, top_new)

    stale = {f"'{o}'": n for o, n in renames.items()} | {f'"{o}"': n for o, n in renames.items()}
    for name in sorted(set(old_nodes) | set(new_nodes)):
        if name in old_nodes and name in new_nodes and renames:
            for change in (found := _setting_changes(name, old_nodes[name], new_nodes[name])):
                before = original.get(name, {}).get(change.key, change.before)
                if isinstance(before, str) and before == change.after and any(q in before for q in stale):
                    change.before = before
                    change.lines = []
                    change.note = "still refers to the old name of a renamed node"
            changes += found
        elif name not in old_nodes:
            node = new_nodes[name]
            changes.append(Change(NODE_ADDED, name, "flow", None, None, node.get("type")))
        elif name not in new_nodes:
            node = old_nodes[name]
            changes.append(Change(NODE_REMOVED, name, "flow", None, node.get("type"), None))
        else:
            changes += _setting_changes(name, old_nodes[name], new_nodes[name])

    old_links, new_links = set(links(old)), set(links(new))
    for link in sorted(old_links - new_links, key=lambda l: l.label()):
        changes.append(Change(LINK_REMOVED, link.source, "flow", "link", link.label(), None))
    for link in sorted(new_links - old_links, key=lambda l: l.label()):
        changes.append(Change(LINK_ADDED, link.source, "flow", "link", None, link.label()))
    return _redact(changes, old, new)


def counts(changes: list[Change]) -> dict[str, int]:
    out = {c: 0 for c in CATEGORIES}
    for change in changes:
        out[change.category] += 1
    return out


def summary(changes: list[Change]) -> str:
    """One line, e.g. `7 change(s) · model 1 · prompt 1 · flow 5` (R4)."""
    parts = [f"{len(changes)} change(s)"] + [f"{c} {n}" for c, n in counts(changes).items()]
    return " · ".join(parts)
