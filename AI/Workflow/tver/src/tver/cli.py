"""`tver` command line. Parses arguments, calls the engine, prints results.

Exit codes (R11): `diff` 0 same · 1 different · 2 error; every other command 0 ok · 2 error.
With `--json` the result (or `{"error": ...}`) is one JSON document on stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from rich.console import Console
from rich.text import Text

from . import engine
from .engine import Change
from .store import Entry, Store, StoreError, resolve_repo, restore, safe_name, save_entry, save_folder, tally

CATEGORY_STYLE = {"model": "magenta", "prompt": "cyan", "flow": "yellow"}
STATUS_STYLE = {"saved": "green bold", "unchanged": "yellow", "skipped": "dim", "refused": "red bold",
                "error": "red bold"}
CONTEXT_WIDTH = 72  # unchanged context lines in a line diff are shortened to this
OK, DIFFERENT, ERROR = 0, 1, 2


class UsageError(Exception):
    pass


def _value(value: Any) -> str:
    if value is None:
        return "(none)"
    return json.dumps(value, ensure_ascii=False)


def _kind(node_type: Any) -> str:
    return str(node_type or "?").rsplit(".", 1)[-1]


def _short(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def emit_json(data: Any) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


# ---------------------------------------------------------------- diff rendering
def render_change(change: Change) -> list[Text]:
    tag = Text(f"[{change.category}]", style=CATEGORY_STYLE[change.category])
    if change.op == engine.NODE_ADDED:
        head = Text.assemble(("+ node  ", "green bold"), (change.node, "bold"), f" ({_kind(change.after)})  ", tag)
    elif change.op == engine.NODE_REMOVED:
        head = Text.assemble(("- node  ", "red bold"), (change.node, "bold"), f" ({_kind(change.before)})  ", tag)
    elif change.op == engine.RENAMED:
        head = Text.assemble(("→ renamed  ", "magenta bold"), (change.before, "bold"), " → ",
                             (change.after, "bold"), "  ", tag)
    elif change.op == engine.LINK_ADDED:
        head = Text.assemble(("+ link  ", "green bold"), change.after, "  ", tag)
    elif change.op == engine.LINK_REMOVED:
        head = Text.assemble(("- link  ", "red bold"), change.before, "  ", tag)
    elif change.lines or change.note:
        head = Text.assemble(("~ ", "blue bold"), (change.node, "bold"), f"  {change.key}  ", tag)
    else:
        head = Text.assemble(("~ ", "blue bold"), (change.node, "bold"), f"  {change.key}: ",
                             (_value(change.before), "red"), " → ", (_value(change.after), "green"), "  ", tag)
    out = [head]
    if change.note:
        out.append(Text(f"    ! {change.note}", style="yellow"))
    for line in change.lines:
        if line.startswith("+ "):
            out.append(Text(f"    {line}", style="green"))
        elif line.startswith("- "):
            out.append(Text(f"    {line}", style="red"))
        else:
            out.append(Text(f"    {_short(line, CONTEXT_WIDTH)}", style="dim"))
    return out


def print_diff(console: Console, title: str, changes: list[Change]) -> None:
    console.print(Text(title, style="bold"))
    console.print()
    for change in changes:
        for line in render_change(change):
            console.print(line)
    if changes:
        console.print()
    console.print(Text(engine.summary(changes), style="bold"))


def diff_json(old: str, new: str, changes: list[Change]) -> dict:
    return {
        "old": old, "new": new, "changed": bool(changes), "total": len(changes),
        "counts": engine.counts(changes), "summary": engine.summary(changes),
        "changes": [asdict(change) for change in changes],
    }


# ---------------------------------------------------------------- commands
def open_store(args: argparse.Namespace) -> Store:
    return Store(resolve_repo(args.repo))


def cmd_diff(args: argparse.Namespace, console: Console) -> int:
    if len(args.targets) == 2:
        old_label, new_label = args.targets
        old = engine.load_workflow(old_label)
        new = engine.load_workflow(new_label)
        title = f"{old.get('name', old_label)}  →  {new.get('name', new_label)}"
    elif len(args.targets) == 3:
        rev1, rev2, name = args.targets
        store = open_store(args)
        old, new = store.read(rev1, name), store.read(rev2, name)
        name = safe_name(name)
        rev1, rev2 = store.resolve_rev(rev1), store.resolve_rev(rev2)
        old_label, new_label = f"{name}@{rev1}", f"{name}@{rev2}"
        title = f"{name}  {rev1}  →  {rev2}"
    else:
        raise UsageError("diff takes OLD.json NEW.json, or REV1 REV2 NAME")
    changes = engine.compare(old, new)
    if args.json:
        emit_json(diff_json(old_label, new_label, changes))
    else:
        print_diff(console, title, changes)
    return DIFFERENT if changes else OK


def print_entries(console: Console, entries: list[Entry], heading: str) -> None:
    console.print(Text(heading, style="bold"))
    for entry in entries:
        name = f" → {entry.name}" if entry.name and entry.status != "skipped" else ""
        rev = f" {entry.rev}" if entry.rev else ""
        console.print(Text.assemble((f"  {entry.status:<9}", STATUS_STYLE[entry.status]),
                                    f" {entry.file}{name}{rev}  ", (entry.detail, "dim")))
    counts = tally(entries)
    console.print(Text(" · ".join(f"{n} {s}" for s, n in counts.items()), style="bold"))


def entries_json(entries: list[Entry], **extra: Any) -> dict:
    return {**extra, "counts": tally(entries), "entries": [asdict(e) for e in entries]}


def cmd_save(args: argparse.Namespace, console: Console) -> int:
    store = open_store(args)
    path = Path(args.file)
    if path.is_dir():
        if args.name:
            raise UsageError("--name works with one file, not a folder")
        entries = save_folder(store, path)
        if args.json:
            emit_json(entries_json(entries, folder=str(path), store=str(store.path)))
        else:
            print_entries(console, entries, f"save {path} → {store.path}")
        return ERROR if any(e.status in ("refused", "error") for e in entries) else OK

    workflow = engine.load_workflow(path)
    name = safe_name(args.name or path.name)
    entry = save_entry(store, workflow, name, path.name)
    if entry.status in ("refused", "error"):
        raise StoreError(entry.detail)
    count = len(store.versions(name))
    if args.json:
        emit_json({**asdict(entry), "versions": count})
    elif entry.status == "unchanged":
        console.print(Text.assemble(("no change", "yellow bold"), f"  {name} {entry.detail}",
                                    (f"  ({count} version(s), nothing committed)", "dim")))
    else:
        console.print(Text.assemble(("saved", "green bold"), f"  {name} ", (entry.rev or "", "bold"),
                                    f"  {entry.detail}", (f"  ({count} version(s))", "dim")))
    return OK


def cmd_log(args: argparse.Namespace, console: Console) -> int:
    store = open_store(args)
    if not args.name:
        store.require()
        counts = {name: len(store.versions(name)) for name in store.names()}
        if args.json:
            emit_json({"store": str(store.path), "workflows": [{"name": n, "versions": c} for n, c in counts.items()]})
            return OK
        console.print(Text(f"store {store.path} · {len(counts)} workflow(s)", style="bold"))
        for name, count in counts.items():
            console.print(f"  {name}  ({count} version(s))")
        return OK
    name = safe_name(Path(args.name).name)
    versions = store.versions(name)
    if not versions:
        raise StoreError(f"no saved versions of '{name}' in {store.path}")
    if args.json:
        emit_json({"name": name, "store": str(store.path),
                   "versions": [{**asdict(v), "summary": v.summary} for v in versions]})
        return OK
    console.print(Text(f"{name} · {len(versions)} version(s) · {store.path}", style="bold"))
    for version in versions:
        console.print(Text.assemble((version.rev, "yellow"), f"  {version.time}  ",
                                    (version.author, "dim"), f"  {version.summary}"))
    return OK


def cmd_restore(args: argparse.Namespace, console: Console) -> int:
    store = open_store(args)
    name = safe_name(args.name)
    store.read(args.rev, name)  # clear error for an unknown name or revision
    rev = store.resolve_rev(args.rev)
    if args.output == "-":
        sys.stdout.write(restore(store, rev, name, None))
        return OK
    output = Path(args.output)
    restore(store, rev, name, output, force=args.force)
    if args.json:
        emit_json({"name": name, "rev": rev, "output": str(output), "versions": len(store.versions(name))})
    else:
        console.print(Text.assemble(("restored", "green bold"), f"  {name} ", (rev, "bold"), f" → {output}",
                                    ("  (store unchanged; review it and import into n8n yourself)", "dim")))
    return OK


def cmd_pull(args: argparse.Namespace, console: Console) -> int:
    from . import n8n

    try:
        if args.file:
            source = str(args.file)
            workflows = n8n.export_from_file(Path(args.file))
        else:
            container = n8n.find_container(args.container)
            source = f"n8n container '{container}' (read-only export)"
            workflows = n8n.export_from_container(container)
    except n8n.N8nError as exc:
        raise StoreError(str(exc)) from None
    store = open_store(args)
    entries = n8n.pull(store, workflows, include_archived=args.include_archived)
    saved = sum(e.status == "saved" for e in entries)
    if args.json:
        emit_json(entries_json(entries, source=source, store=str(store.path), new_versions=saved))
    else:
        print_entries(console, entries, f"pull {source} → {store.path}")
        console.print(Text(f"{saved} new version(s)", style="bold green" if saved else "bold"))
    return ERROR if any(e.status in ("refused", "error") for e in entries) else OK


# ---------------------------------------------------------------- parsing
REPO_HELP = "version store (default: $TVER_REPO, else ~/.tver/store)"
JSON_HELP = "print one JSON document for programs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tver",
        usage="tver [--repo REPO] [--json] COMMAND ...  |  tver [--repo REPO] FILE [-n NAME]",
        description="Compare n8n workflows by meaning (nodes, settings, links) and keep versions.",
        epilog="tver FILE opens the terminal screen: saved versions of FILE, changes per node, "
               "before/after detail; press s to save FILE.  Exit codes: diff 0 same, 1 different, 2 error; "
               "other commands 0 ok, 2 error.",
    )
    parser.add_argument("--repo", help=REPO_HELP)
    parser.add_argument("--json", action="store_true", help=JSON_HELP)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=argparse.SUPPRESS, help=REPO_HELP)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=JSON_HELP)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    diff = sub.add_parser("diff", parents=[common], help="compare two files, or two saved versions",
                          usage="tver diff OLD.json NEW.json  |  tver diff REV1 REV2 NAME")
    diff.add_argument("targets", nargs="+", metavar="ARG", help="two workflow files, or REV1 REV2 NAME")
    diff.set_defaults(run=cmd_diff)

    save = sub.add_parser("save", parents=[common],
                          help="save a workflow (or every workflow in a folder) if it changed")
    save.add_argument("file", help="workflow JSON, or a folder of them")
    save.add_argument("-n", "--name", help="name in the store (default: file name)")
    save.set_defaults(run=cmd_save)

    log = sub.add_parser("log", parents=[common], help="list saved versions of a workflow")
    log.add_argument("name", nargs="?", help="workflow name (omit to list all workflows)")
    log.set_defaults(run=cmd_log)

    rest = sub.add_parser("restore", parents=[common], help="write a saved version to a file (store unchanged)")
    rest.add_argument("rev", help="revision from `tver log`")
    rest.add_argument("name", help="workflow name")
    rest.add_argument("-o", "--output", required=True, help="output file, or - for stdout")
    rest.add_argument("--force", action="store_true", help="overwrite an existing output file")
    rest.set_defaults(run=cmd_restore)

    pull = sub.add_parser("pull", parents=[common], help="save every workflow of a running n8n (read-only)")
    pull.add_argument("--container", help="n8n docker container (default: $TVER_N8N_CONTAINER, else the "
                                          "running compose service 'n8n')")
    pull.add_argument("--file", help="read an `n8n export:workflow --all` output file instead of docker")
    pull.add_argument("--include-archived", action="store_true", help="also save archived workflows")
    pull.set_defaults(run=cmd_pull)
    return parser


COMMANDS = ("diff", "save", "log", "restore", "pull")


def first_positional(argv: Sequence[str]) -> str | None:
    skip = False
    for token in argv:
        if skip:
            skip = False
        elif token == "--repo":
            skip = True
        elif not token.startswith("-"):
            return token
    return None


def build_tui_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tver", description="Terminal screen for one workflow file.")
    parser.add_argument("--repo", help=REPO_HELP)
    parser.add_argument("file", help="workflow JSON to browse and save")
    parser.add_argument("-n", "--name", help="name in the store (default: file name)")
    return parser


def run_tui(argv: Sequence[str]) -> int:
    args = build_tui_parser().parse_args(argv)
    file = Path(args.file)
    if not file.is_file():
        Console(stderr=True, highlight=False, soft_wrap=True).print(
            Text.assemble(("error: ", "red bold"), f"{file}: file not found"))
        return ERROR
    from .tui import TverApp  # Textual loads only for the screen

    TverApp(open_store(args), file, safe_name(args.name or file.name)).run()
    return OK


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    target = first_positional(argv)
    if target is not None and target not in COMMANDS:
        return run_tui(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "run", None):
        parser.print_help()
        return ERROR
    console = Console(highlight=False, soft_wrap=True)
    try:
        return args.run(args, console)
    except UsageError as exc:
        parser.error(str(exc))
    except (engine.WorkflowError, StoreError) as exc:
        if args.json:
            emit_json({"error": str(exc)})
        else:
            Console(stderr=True, highlight=False, soft_wrap=True).print(
                Text.assemble(("error: ", "red bold"), str(exc)))
    return ERROR


if __name__ == "__main__":
    sys.exit(main())
