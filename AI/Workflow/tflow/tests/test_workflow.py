import json
from pathlib import Path

import pytest

from tflow.render import render_markdown, render_mermaid, render_tree
from tflow.workflow import load_workflow


SAMPLES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("name", "nodes", "connections"),
    [
        ("meeting-agent.json", 7, 6),
        ("it-agent.json", 14, 14),
        ("lab03-example2-isolated.json", 18, 20),
    ],
)
def test_sample_counts_and_text(name, nodes, connections):
    workflow = load_workflow(SAMPLES / name)
    assert (len(workflow.nodes), len(workflow.connections)) == (nodes, connections)
    tree = render_tree(workflow)
    assert "[true]" in tree and "[false]" in tree
    assert len(tree.splitlines()) <= nodes + 6


def test_switch_labels_and_join():
    workflow = load_workflow(SAMPLES / "lab03-example2-isolated.json")
    tree = render_tree(workflow)
    assert all(f"[{label}]" in tree for label in ("it", "meeting", "other", "needs input"))
    assert "Collect results (다시 합류/반복)" in tree
    diagram = render_mermaid(workflow)
    assert '-->|"needs input"|' in diagram
    assert "Route by type" in diagram
    assert "n7" in diagram


def test_cycle_and_unsafe_names(tmp_path):
    path = tmp_path / "loop.json"
    path.write_text(json.dumps({
        "name": "loop",
        "nodes": [
            {"name": "Start? (시작)", "type": "n8n-nodes-base.webhook"},
            {"name": 'A "quote"', "type": "n8n-nodes-base.code"},
        ],
        "connections": {
            "Start? (시작)": {"main": [[{"node": 'A "quote"'}]]},
            'A "quote"': {"main": [[{"node": "Start? (시작)"}]]},
        },
    }), encoding="utf-8")
    workflow = load_workflow(path)
    tree = render_tree(workflow)
    assert "Start? (시작) (다시 합류/반복)" in tree
    diagram = render_mermaid(workflow)
    assert 'n0["Start? (시작)"]' in diagram
    assert '&quot;quote&quot;' in diagram
    assert 'Start? (시작) -->' not in diagram
    assert "```mermaid" in render_markdown(workflow)
