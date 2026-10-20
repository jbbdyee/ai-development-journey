from pathlib import Path

from rich.cells import cell_len

from tflow.flow_map import BOX_WIDTH, layout_flow, render_flow
from tflow.workflow import Connection, Workflow, load_workflow


SOURCE = Path(__file__).parent / "fixtures/assistant.json"


def test_assistant_is_two_dimensional_and_rejoins_once():
    workflow = load_workflow(SOURCE)
    layout = layout_flow(workflow)
    assert len(layout.boxes) == 18
    assert len([edge for edge in layout.edges if edge.target == "Collect results"]) == 4
    assert layout.boxes["Call IT agent"].x != layout.boxes["Has meeting notes?"].x
    assert layout.boxes["Route by type"].y < layout.boxes["Collect results"].y
    assert "OpenAI chat model" not in layout.boxes
    assert len(layout.notes) == 9
    lines = render_flow(layout, workflow).plain.splitlines()
    for box in layout.boxes.values():
        assert lines[box.y][box.x:box.x + BOX_WIDTH].startswith("┌")
        assert lines[box.y + 1][box.x:box.x + BOX_WIDTH].startswith("│")
        assert lines[box.y + 2][box.x:box.x + BOX_WIDTH].startswith("└")
    assert all(label in "\n".join(lines) for label in ("true", "false", "it", "meeting", "other"))


def test_cycle_is_a_reference_and_wide_name_keeps_box_width():
    workflow = Workflow("cycle", [
        {"name": "시작 노드", "type": "n8n-nodes-base.webhook"},
        {"name": "분기", "type": "n8n-nodes-base.if"},
        {"name": "긴 이름을 가진 처리 노드", "type": "n8n-nodes-base.set"},
        {"name": "Other", "type": "n8n-nodes-base.set"},
    ], [
        Connection("시작 노드", "분기", "main", 0, 0),
        Connection("분기", "긴 이름을 가진 처리 노드", "main", 0, 0),
        Connection("분기", "Other", "main", 1, 0),
        Connection("긴 이름을 가진 처리 노드", "분기", "main", 0, 0),
    ])
    layout = layout_flow(workflow)
    assert len(layout.boxes) == 4 and len(layout.cycles) == 1
    assert layout.boxes["긴 이름을 가진 처리 노드"].x != layout.boxes["Other"].x
    lines = render_flow(layout, workflow).plain.splitlines()
    assert "↩" in "\n".join(lines)
    box = layout.boxes["긴 이름을 가진 처리 노드"]
    assert cell_len(lines[box.y + 1][:box.x + BOX_WIDTH]) >= box.x + BOX_WIDTH
