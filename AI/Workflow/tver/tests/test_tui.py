import asyncio
import html
import io
import json
import re
import shutil
from pathlib import Path

from rich.console import Console
from textual.widgets import ListView, Tree

from tver import engine
from tver.store import Store
from tver.tui import TverApp, change_detail

from .conftest import DATA

SIZE = (140, 44)


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def two_versions(store_path: Path, tmp_path: Path) -> Path:
    store = Store(store_path)
    store.save(load("helpdesk-v1.json"), "helpdesk")
    store.save(load("helpdesk-v2.json"), "helpdesk")
    current = tmp_path / "helpdesk.json"
    shutil.copy(DATA / "helpdesk-v2.json", current)
    return current


def plain(renderable) -> str:
    console = Console(width=200, record=True, color_system=None, file=io.StringIO())
    console.print(renderable)
    return console.export_text()


def screen_text(app) -> str:
    """What the terminal shows, as plain text (from Textual's own screenshot)."""
    svg = app.export_screenshot()
    rows = re.findall(r'<g class="[^"]*-matrix">(.*?)</g>', svg, re.S)
    body = rows[0] if rows else svg
    return html.unescape(re.sub(r"<[^>]+>", "", body)).replace("\xa0", " ")


async def settle(app, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def leaves(tree: Tree) -> list:
    return [leaf.data for branch in tree.root.children for leaf in branch.children]


def run(coro):
    return asyncio.run(coro)


def test_list_tree_and_detail(isolated_store, tmp_path):
    current = two_versions(isolated_store, tmp_path)

    async def scenario():
        app = TverApp(Store(isolated_store), current, "helpdesk")
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            versions = app.query_one("#versions", ListView)
            assert len(versions.children) == 2 and versions.index == 0

            tree = app.query_one("#changes", Tree)
            changes = leaves(tree)
            assert engine.summary(changes) == "7 change(s) · model 1 · prompt 1 · flow 5"
            assert [b.label.plain.split("  ")[0] for b in tree.root.children] == \
                ["Answer", "Answer model", "Question webhook", "Review check"]

            # the first change is highlighted and shown: the prompt line diff
            assert app.detail_change.key == "parameters.options.systemMessage"
            screen = screen_text(app)
            assert "FAQ-003" in screen and "Versions (2)" in screen
            assert "same as latest version #2" in screen

            # moving down the tree shows before/after of the model change
            tree.focus()
            for _ in range(10):
                if app.detail_change.category == "model":
                    break
                await pilot.press("down")
                await pilot.pause()
            assert app.detail_change.key == "parameters.model.value"
            text = plain(change_detail(app.detail_change, *app.pair))
            assert "before  gpt-4.1-mini" in text and "after   gpt-5.4-nano" in text

            # older version: compared with nothing, every node is added
            versions.focus()
            await pilot.press("down")
            await settle(app, pilot)
            first = leaves(app.query_one("#changes", Tree))
            assert sum(c.op == engine.NODE_ADDED for c in first) == 9
            assert app.shown_rev == Store(isolated_store).versions("helpdesk")[1].rev

    run(scenario())


def test_detail_renders_line_diff():
    old, new = load("helpdesk-v1.json"), load("helpdesk-v2.json")
    change = next(c for c in engine.compare(old, new) if c.category == "prompt")
    text = plain(change_detail(change, engine.clean(old), engine.clean(new)))
    assert any(line.startswith("+ ") and "[FAQ-003]" in line for line in text.splitlines())


def test_s_saves_new_change_and_skips_same(isolated_store, tmp_path):
    current = two_versions(isolated_store, tmp_path)
    edited = load("helpdesk-v2.json")
    next(n for n in edited["nodes"] if n["name"] == "Answer model")["parameters"]["options"]["temperature"] = 0.3
    current.write_text(json.dumps(edited), encoding="utf-8")

    async def scenario():
        app = TverApp(Store(isolated_store), current, "helpdesk")
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            assert "1 change(s)" in screen_text(app)  # pending change shown in status
            await pilot.press("s")
            await settle(app, pilot)
            assert len(app.query_one("#versions", ListView).children) == 3
            changes = leaves(app.query_one("#changes", Tree))
            assert [(c.node, c.key) for c in changes] == [("Answer model", "parameters.options.temperature")]
            await pilot.press("s")
            await settle(app, pilot)
            assert len(app.query_one("#versions", ListView).children) == 3

    run(scenario())
    assert len(Store(isolated_store).versions("helpdesk")) == 3


def test_empty_store_first_save(isolated_store, tmp_path):
    current = tmp_path / "helpdesk.json"
    shutil.copy(DATA / "helpdesk-v1.json", current)

    async def scenario():
        app = TverApp(Store(isolated_store), current, "helpdesk")
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            assert len(app.query_one("#versions", ListView).children) == 0
            assert "not saved yet" in screen_text(app)
            await pilot.press("s")
            await settle(app, pilot)
            assert len(app.query_one("#versions", ListView).children) == 1
            assert sum(c.op == engine.NODE_ADDED for c in leaves(app.query_one("#changes", Tree))) == 9

    run(scenario())
    assert not (tmp_path / "home" / ".tver").exists()


def test_cli_routes_file_to_tui(monkeypatch, isolated_store, tmp_path):
    from tver import cli, tui

    seen = {}
    monkeypatch.setattr(tui.TverApp, "run", lambda self: seen.update(name=self.workflow_name, repo=self.store.path))
    current = tmp_path / "Help Desk.json"
    shutil.copy(DATA / "helpdesk-v1.json", current)
    assert cli.main([str(current)]) == 0
    assert seen == {"name": "help-desk", "repo": isolated_store.resolve()}
    assert cli.main(["--repo", str(tmp_path / "x"), str(current), "-n", "helpdesk"]) == 0
    assert seen == {"name": "helpdesk", "repo": (tmp_path / "x").resolve()}
    assert cli.main([str(tmp_path / "missing.json")]) == 2


def test_renamed_and_secret_safe_labels():
    from tver.tui import change_label

    change = engine.Change(engine.RENAMED, "Find FAQ", "flow", None, "Search FAQ", "Find FAQ")
    assert change_label(change).plain == "→ renamed from Search FAQ [flow]"
    empty = {"nodes": [], "connections": {}}
    text = plain(change_detail(change, empty, empty))
    assert "before  Search FAQ" in text and "after   Find FAQ" in text
