"""R12: a node renamed without other changes is one `renamed`."""

import copy
import json

from tver import engine
from tver.cli import main


def rename(v1: dict, old: str, new: str, references: bool) -> dict:
    wf = copy.deepcopy(v1)
    if references:  # what n8n does when a node is renamed in the editor
        wf = json.loads(json.dumps(wf, ensure_ascii=False).replace(f"$('{old}')", f"$('{new}')"))
    for node in wf["nodes"]:
        if node["name"] == old:
            node["name"] = new
    wf["connections"][new] = wf["connections"].pop(old)
    for outputs in wf["connections"].values():
        for slots in outputs.values():
            for targets in slots:
                for target in targets:
                    if target["node"] == old:
                        target["node"] = new
    return wf


def test_rename_like_n8n_is_one_change(v1):
    changes = engine.compare(v1, rename(v1, "Search FAQ", "Find FAQ", references=True))
    assert [(c.op, c.before, c.after) for c in changes] == [("renamed", "Search FAQ", "Find FAQ")]
    assert engine.summary(changes) == "1 change(s) · model 0 · prompt 0 · flow 1"


def test_rename_leaving_stale_references_reports_them(v1):
    changes = engine.compare(v1, rename(v1, "Search FAQ", "Find FAQ", references=False))
    assert changes[0].op == "renamed"
    stale = [c for c in changes[1:]]
    assert {c.node for c in stale} == {"Answer", "Build result"}
    assert all(c.note and "$('Search FAQ')" in c.after and c.before == c.after for c in stale)


def test_rename_plus_edit_is_remove_and_add(v1):
    wf = rename(v1, "Search FAQ", "Find FAQ", references=True)
    next(n for n in wf["nodes"] if n["name"] == "Find FAQ")["parameters"]["url"] = "http://other/faq"
    ops = {c.op for c in engine.compare(v1, wf)}
    assert "renamed" not in ops and {"node_added", "node_removed"} <= ops


def test_two_identical_nodes_pair_once(v1):
    wf = copy.deepcopy(v1)
    clone = copy.deepcopy(next(n for n in wf["nodes"] if n["name"] == "Reject empty"))
    clone["name"] = "Reject empty 2"
    wf["nodes"].append(clone)
    base = copy.deepcopy(wf)
    for node in wf["nodes"]:
        node["name"] = {"Reject empty": "Reject A", "Reject empty 2": "Reject B"}.get(node["name"], node["name"])
    wf["connections"]["Has question?"]["main"][1][0]["node"] = "Reject A"
    renamed = [c for c in engine.compare(base, wf) if c.op == "renamed"]
    assert sorted((c.before, c.after) for c in renamed) == [("Reject empty", "Reject A"), ("Reject empty 2", "Reject B")]


def test_cli_shows_renamed(tmp_path, capsys, v1):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(v1), encoding="utf-8")
    b.write_text(json.dumps(rename(v1, "Search FAQ", "Find FAQ", references=True)), encoding="utf-8")
    assert main(["diff", str(a), str(b)]) == 1
    out = capsys.readouterr().out
    assert "→ renamed  Search FAQ → Find FAQ  [flow]" in out
