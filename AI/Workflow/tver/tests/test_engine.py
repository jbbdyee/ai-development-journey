import copy
import json
import random

import pytest

from tver import engine
from tver.engine import Change, WorkflowError

from .conftest import DATA


def ops(changes: list[Change]) -> list[tuple]:
    return [(c.op, c.node, c.key, c.category) for c in changes]


# ---------------------------------------------------------------- R1 · R4 reference
def test_reference_v1_v2_has_seven_changes(v1, v2):
    changes = engine.compare(v1, v2)
    assert len(changes) == 7
    assert engine.counts(changes) == {"model": 1, "prompt": 1, "flow": 5}
    assert engine.summary(changes) == "7 change(s) · model 1 · prompt 1 · flow 5"


def test_reference_change_details(v1, v2):
    changes = engine.compare(v1, v2)
    assert sorted(ops(changes)) == sorted([
        ("changed", "Answer", "parameters.options.systemMessage", "prompt"),
        ("changed", "Answer model", "parameters.model.value", "model"),
        ("changed", "Question webhook", "parameters.path", "flow"),
        ("node_added", "Review check", None, "flow"),
        ("link_removed", "Answer", "link", "flow"),
        ("link_added", "Answer", "link", "flow"),
        ("link_added", "Review check", "link", "flow"),
    ])
    by_key = {c.key: c for c in changes if c.op == "changed"}
    assert by_key["parameters.model.value"].before == "gpt-4.1-mini"
    assert by_key["parameters.model.value"].after == "gpt-5.4-nano"
    assert by_key["parameters.path"].before == "rel-v1"
    links = {(c.op, c.before or c.after) for c in changes if c.key == "link"}
    assert links == {
        ("link_removed", "Answer → Build result (main)"),
        ("link_added", "Answer → Review check (main)"),
        ("link_added", "Review check → Build result (main)"),
    }


def test_removed_node_and_reverse_direction(v1, v2):
    changes = engine.compare(v2, v1)
    assert engine.summary(changes) == "7 change(s) · model 1 · prompt 1 · flow 5"
    assert ("node_removed", "Review check", None, "flow") in ops(changes)


# ---------------------------------------------------------------- R3 line diff
def test_system_message_shows_added_faq_line(v1, v2):
    change = next(c for c in engine.compare(v1, v2) if c.key == "parameters.options.systemMessage")
    added = [line for line in change.lines if line.startswith("+ ")]
    assert len(added) == 1 and "[FAQ-003]" in added[0]
    assert not [line for line in change.lines if line.startswith("- ")]


def test_short_values_have_no_line_diff(v1, v2):
    change = next(c for c in engine.compare(v1, v2) if c.key == "parameters.path")
    assert change.lines == []


def test_long_single_line_uses_line_diff():
    a, b = "x" * 81, "y" * 81
    assert engine.is_long(a) and not engine.is_long("x" * 80)
    assert engine.line_diff(a, b) == [f"- {a}", f"+ {b}"]


def test_line_diff_against_missing_value():
    assert engine.line_diff(None, "one\ntwo") == ["+ one", "+ two"]


# ---------------------------------------------------------------- R2 meaningless differences
def test_moved_fixture_has_no_changes(v1):
    moved = json.loads((DATA / "helpdesk-v1-moved.json").read_text(encoding="utf-8"))
    assert moved["nodes"][0]["name"] != v1["nodes"][0]["name"]  # order really differs
    assert engine.compare(v1, moved) == []


def _shuffle_keys(value, rng):
    if isinstance(value, dict):
        keys = list(value)
        rng.shuffle(keys)
        return {k: _shuffle_keys(value[k], rng) for k in keys}
    if isinstance(value, list):
        return [_shuffle_keys(v, rng) for v in value]
    return value


@pytest.mark.parametrize("seed", range(5))
def test_random_ids_positions_and_order_are_ignored(v2, seed):
    rng = random.Random(seed)
    other = copy.deepcopy(v2)
    for node in other["nodes"]:
        node["id"] = f"id-{rng.random()}"
        node["position"] = [rng.randint(-999, 999), rng.randint(-999, 999)]
        node["webhookId"] = f"hook-{rng.random()}"
    rng.shuffle(other["nodes"])
    other.update(versionId="v-x", updatedAt="2030-01-01", id="wf-x", meta={"instanceId": "abc"})
    assert engine.compare(v2, _shuffle_keys(other, rng)) == []


def test_connection_target_order_is_ignored(v1):
    other = copy.deepcopy(v1)
    other["connections"]["Has question?"]["main"][0].append(
        {"node": "Reject empty", "type": "main", "index": 0})
    twisted = copy.deepcopy(other)
    twisted["connections"]["Has question?"]["main"][0].reverse()
    assert engine.compare(other, twisted) == []


def test_list_order_inside_parameters_still_counts(v1):
    other = copy.deepcopy(v1)
    params = next(n for n in other["nodes"] if n["name"] == "Get ticket")["parameters"]
    params["queryParameters"]["parameters"].insert(0, {"name": "extra", "value": "1"})
    assert len(engine.compare(v1, other)) > 0


# ---------------------------------------------------------------- clean
def test_clean_is_idempotent_and_drops_meta(v1):
    once = engine.clean(v1)
    assert engine.clean(once) == once
    assert engine.dumps(engine.clean(once)) == engine.dumps(once)
    for node in once["nodes"]:
        assert not engine.NODE_META & set(node)
    assert [n["name"] for n in once["nodes"]] == sorted(n["name"] for n in v1["nodes"])
    assert engine.compare(once, v1) == []


def test_output_index_kept_in_links(v1):
    labels = [link.label() for link in engine.links(v1)]
    assert "Has question?[1] → Reject empty (main)" in labels
    assert "Answer model → Answer (ai_languageModel)" in labels


# ---------------------------------------------------------------- categories
@pytest.mark.parametrize("node_type, key, expected", [
    ("@n8n/n8n-nodes-langchain.lmChatOpenAi", "parameters.model.value", "model"),
    ("@n8n/n8n-nodes-langchain.lmChatOpenAi", "parameters.model", "model"),
    ("@n8n/n8n-nodes-langchain.lmChatOpenAi", "parameters.options.temperature", "flow"),
    ("@n8n/n8n-nodes-langchain.agent", "parameters.options.systemMessage", "prompt"),
    ("@n8n/n8n-nodes-langchain.agent", "parameters.text", "prompt"),
    ("@n8n/n8n-nodes-langchain.agent", "parameters.options.maxIterations", "flow"),
    ("n8n-nodes-base.code", "parameters.jsCode", "prompt"),
    ("n8n-nodes-base.httpRequest", "parameters.url", "flow"),
    ("n8n-nodes-base.httpRequest", "parameters.model", "flow"),
])
def test_category_rules(node_type, key, expected):
    assert engine.category({"type": node_type}, key) == expected


def test_workflow_settings_change_is_flow(v1):
    other = copy.deepcopy(v1)
    other["settings"]["executionOrder"] = "v0"
    assert ops(engine.compare(v1, other)) == [("changed", "(workflow)", "settings.executionOrder", "flow")]


def test_workflow_name_is_not_a_change(v1):
    other = copy.deepcopy(v1)
    other["name"] = "renamed workflow"
    assert engine.compare(v1, other) == []


# ---------------------------------------------------------------- validation
def test_load_rejects_non_workflows(tmp_path):
    (tmp_path / "bad.json").write_text("{nope")
    (tmp_path / "list.json").write_text("[]")
    (tmp_path / "notes.json").write_text('{"cases": []}')
    (tmp_path / "dup.json").write_text('{"nodes": [{"name": "a"}, {"name": "a"}], "connections": {}}')
    for name, words in [("bad.json", "invalid JSON"), ("list.json", "object"),
                        ("notes.json", "not an n8n workflow"), ("dup.json", "duplicate"),
                        ("missing.json", "not found")]:
        with pytest.raises(WorkflowError, match=words):
            engine.load_workflow(tmp_path / name)
