"""`tver FILE` terminal screen (R8).

Left: saved versions. Right: node-by-node changes of the selected version
against the one before it. Bottom: before/after or line diff of the selected
change. `s` saves FILE. All comparing and saving goes through engine/store.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static, Tree

from . import engine
from .engine import Change
from .store import Store, StoreError, Version

EMPTY = {"nodes": [], "connections": {}}
OP_MARK = {
    engine.NODE_ADDED: ("+", "green"), engine.NODE_REMOVED: ("-", "red"), engine.CHANGED: ("~", "blue"),
    engine.LINK_ADDED: ("+", "green"), engine.LINK_REMOVED: ("-", "red"), engine.RENAMED: ("→", "magenta"),
}
CATEGORY_STYLE = {"model": "magenta", "prompt": "cyan", "flow": "yellow"}


def change_label(change: Change) -> Text:
    mark, style = OP_MARK[change.op]
    if change.op == engine.NODE_ADDED:
        body = f"node added ({str(change.after).rsplit('.', 1)[-1]})"
    elif change.op == engine.NODE_REMOVED:
        body = f"node removed ({str(change.before).rsplit('.', 1)[-1]})"
    elif change.op == engine.RENAMED:
        body = f"renamed from {change.before}"
    elif change.op in (engine.LINK_ADDED, engine.LINK_REMOVED):
        body = f"link {change.after or change.before}"
    else:
        body = str(change.key)
    return Text.assemble((f"{mark} ", f"bold {style}"), body, " ",
                         (f"[{change.category}]", CATEGORY_STYLE[change.category]))


def _pretty(value: Any) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def change_detail(change: Change, old: dict, new: dict) -> Group:
    """Before/after, or the line diff, for one change."""
    title = Text.assemble((change.node, "bold"), "  ", change_label(change))
    parts: list[Any] = [title, Text("")]
    if change.note:
        parts.append(Text(f"! {change.note}", style="yellow"))
    if change.op in (engine.NODE_ADDED, engine.NODE_REMOVED):
        source = new if change.op == engine.NODE_ADDED else old
        node = next((n for n in source["nodes"] if n["name"] == change.node), {})
        parts.append(Text(_pretty(node), style="green" if change.op == engine.NODE_ADDED else "red"))
    elif change.op == engine.RENAMED:
        parts.append(Text.assemble(("before  ", "bold red"), str(change.before)))
        parts.append(Text.assemble(("after   ", "bold green"), str(change.after)))
    elif change.lines:
        for line in change.lines:
            style = "green" if line.startswith("+ ") else "red" if line.startswith("- ") else "dim"
            parts.append(Text(line, style=style))
    else:
        parts.append(Text.assemble(("before  ", "bold red"), _pretty(change.before)))
        parts.append(Text.assemble(("after   ", "bold green"), _pretty(change.after)))
    return Group(*parts)


class VersionItem(ListItem):
    def __init__(self, version: Version, number: int) -> None:
        super().__init__(Label(Text.assemble(
            (f"#{number} ", "bold"), (version.rev, "yellow"), f"  {version.time}\n   ",
            (version.summary, "dim"))))
        self.version = version


class TverApp(App):
    TITLE = "tver"
    CSS = """
    #top { height: 3fr; }
    #versions-box { width: 50; border: round $primary; }
    #changes-box { border: round $primary; }
    #detail-box { height: 2fr; border: round $secondary; }
    #versions-box, #changes-box, #detail-box { border-title-style: bold; }
    #status { height: 1; padding: 0 1; background: $boost; }
    VersionItem { padding: 0 1; }
    """
    BINDINGS = [
        Binding("s", "save", "Save file"),
        Binding("r", "reload", "Reload"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, store: Store, file: Path, name: str) -> None:
        super().__init__()
        self.store = store
        self.file = Path(file)
        self.workflow_name = name
        self.versions: list[Version] = []
        self.pair: tuple[dict, dict] = (EMPTY, EMPTY)
        self.shown_rev: str | None = None
        self.detail_change: Change | None = None

    # ------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top"):
            with Vertical(id="versions-box"):
                yield ListView(id="versions")
            with Vertical(id="changes-box"):
                tree: Tree[Change | None] = Tree("changes", id="changes")
                tree.show_root = False
                yield tree
        with VerticalScroll(id="detail-box"):
            yield Static("", id="detail")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"{self.workflow_name} · {self.file}"
        self.query_one("#versions-box").border_title = "Versions"
        self.query_one("#changes-box").border_title = "Changes"
        self.query_one("#detail-box").border_title = "Detail"
        self.load_versions()

    # ------------------------------------------------------------ versions
    def set_status(self, text: str, style: str = "") -> None:
        self.query_one("#status", Static).update(Text(text, style=style))

    def load_versions(self, select_rev: str | None = None) -> None:
        try:
            self.versions = self.store.versions(self.workflow_name) if self.store.exists() else []
        except StoreError as exc:
            self.versions = []
            self.set_status(f"error: {exc}", "red")
        view = self.query_one("#versions", ListView)
        view.clear()
        total = len(self.versions)
        view.extend(VersionItem(v, total - i) for i, v in enumerate(self.versions))
        self.query_one("#versions-box").border_title = f"Versions ({total})"
        if not self.versions:
            self.show_changes(EMPTY, EMPTY, [], None)
            self.query_one("#detail", Static).update(
                Text(f"No saved versions of '{self.workflow_name}' in {self.store.path}.\nPress s to save {self.file.name}."))
            return
        index = next((i for i, v in enumerate(self.versions) if v.rev == select_rev), 0)
        view.index = index
        view.focus()
        self.compare_version(index)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "versions" and event.list_view.index is not None:
            self.compare_version(event.list_view.index)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "versions":
            self.query_one("#changes", Tree).focus()

    @work(thread=True, exclusive=True, group="compare")
    def compare_version(self, index: int) -> None:
        """Read the chosen version and the one before it, compare in a worker."""
        if index >= len(self.versions):
            return
        version = self.versions[index]
        try:
            new = self.store.read(version.rev, self.workflow_name)
            old = (self.store.read(self.versions[index + 1].rev, self.workflow_name)
                   if index + 1 < len(self.versions) else EMPTY)
            changes = engine.compare(old, new)
        except (StoreError, engine.WorkflowError) as exc:
            self.call_from_thread(self.set_status, f"error: {exc}", "red")
            return
        self.call_from_thread(self.show_changes, old, new, changes, version)

    # ------------------------------------------------------------ changes
    def show_changes(self, old: dict, new: dict, changes: list[Change], version: Version | None) -> None:
        self.pair = (old, new)
        self.shown_rev = version.rev if version else None
        tree = self.query_one("#changes", Tree)
        tree.clear()
        groups: dict[str, list[Change]] = {}
        for change in changes:
            groups.setdefault(change.node, []).append(change)
        first = None
        for node, items in groups.items():
            counts = engine.counts(items)
            tags = " ".join(f"{c} {n}" for c, n in counts.items() if n)
            branch = tree.root.add(Text.assemble((node, "bold"), f"  ({tags})"), data=None, expand=True)
            for change in items:
                leaf = branch.add_leaf(change_label(change), data=change)
                first = first or leaf
        box = self.query_one("#changes-box")
        if version is None:
            box.border_title = "Changes"
        else:
            against = "first version" if old is EMPTY else "vs previous"
            box.border_title = f"Changes · {version.rev} {against} · {engine.summary(changes)}"
        detail = self.query_one("#detail", Static)
        if first is not None:
            tree.move_cursor(first)
            self.show_detail(first.data)
        elif version is not None:
            detail.update(Text("No meaningful changes."))
        self.refresh_status()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if isinstance(event.node.data, Change):
            self.show_detail(event.node.data)

    def show_detail(self, change: Change) -> None:
        self.detail_change = change
        old, new = self.pair
        self.query_one("#detail", Static).update(change_detail(change, old, new))
        self.query_one("#detail-box", VerticalScroll).scroll_home(animate=False)

    # ------------------------------------------------------------ current file
    def refresh_status(self) -> None:
        try:
            current = engine.load_workflow(self.file)
        except engine.WorkflowError as exc:
            self.set_status(f"current file: {exc}", "red")
            return
        if not self.versions:
            self.set_status(f"{self.file.name}: not saved yet · press s to save", "yellow")
            return
        try:
            latest = self.store.read(self.versions[0].rev, self.workflow_name)
        except StoreError as exc:
            self.set_status(f"error: {exc}", "red")
            return
        pending = engine.compare(latest, current)
        if pending:
            self.set_status(f"{self.file.name}: {engine.summary(pending)} since #{len(self.versions)} · press s to save",
                            "yellow")
        else:
            self.set_status(f"{self.file.name}: same as latest version #{len(self.versions)}", "green")

    def action_save(self) -> None:
        try:
            result = self.store.save(engine.load_workflow(self.file), self.workflow_name)
        except (StoreError, engine.WorkflowError) as exc:
            self.set_status(f"save failed: {exc}", "red")
            self.notify(str(exc), title="save failed", severity="error")
            return
        if result.saved:
            self.load_versions(select_rev=result.rev)
            self.notify(f"saved {result.rev}", title="tver")
        else:
            self.notify(f"no change · matches {result.rev}", title="tver")
            self.refresh_status()

    def action_reload(self) -> None:
        self.load_versions(select_rev=self.shown_rev)
