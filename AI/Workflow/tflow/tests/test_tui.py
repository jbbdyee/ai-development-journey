from pathlib import Path
import asyncio

from textual.widgets import Static, Tree

from tflow.details import node_details
from tflow.explanations import DescriptionCache, DescriptionService
from tflow.flow_map import BOX_WIDTH, layout_flow, render_flow
from tflow.render import render_markdown
from tflow.tui import FlowMap, TflowApp, _safe_display
from tflow.workflow import Connection, Workflow, load_workflow


SAMPLES = Path(__file__).parent / "fixtures"


def test_agent_attachments_and_details():
    workflow = load_workflow(SAMPLES / "it-agent.json")
    assert workflow.warnings() == []
    attached = workflow.attachments("IT help agent")
    assert attached == {
        "ai_languageModel": ["OpenAI chat model"],
        "ai_tool": ["Search FAQ", "Get ticket"],
    }
    details = node_details(workflow, "IT help agent")
    for text in ("지시문:", "OpenAI chat model", "Search FAQ", "Get ticket"):
        assert text in details
    assert "credentials" not in details.lower()
    assert "방식: POST" in node_details(workflow, "IT question webhook")
    assert "경로: /it-agent" in node_details(workflow, "IT question webhook")
    assert "조건:" in node_details(workflow, "Has question?")
    assert "코드:" in node_details(workflow, "Check answer")


def test_broken_workflow_warnings():
    workflow = load_workflow(Path(__file__).parent / "fixtures/broken-workflow.json")
    assert workflow.warnings() == [
        "없는 연결 대상: Start → Finsh",
        "고립된 노드: Finish",
        "고립된 노드: Unused",
    ]


def test_sticky_note_excluded_but_invalid_branch_warned():
    source = SAMPLES / "assistant.json"
    workflow = load_workflow(source)
    assert workflow.warnings() == []
    workflow.connections.append(Connection("Has message?", "Split tasks", "main", 2, 0))
    assert "잘못된 분기: Has message? 출력 2" in workflow.warnings()
    workflow.connections.append(Connection("Has message?", "Absent", "main", 0, 0))
    assert "없는 연결 대상: Has message? → Absent" in workflow.warnings()


def test_tui_selection_and_quit():
    asyncio.run(_exercise_tui())


async def _exercise_tui():
    path = SAMPLES / "it-agent.json"
    app = TflowApp(load_workflow(path), path)
    async with app.run_test() as pilot:
        tree = app.query_one("#flow-tree", Tree)
        def descendants(node):
            yield node
            for child in node.children:
                yield from descendants(child)

        assert "IT help agent" in [node.data for node in descendants(tree.root)]
        agent = next(node for node in descendants(tree.root) if node.data == "IT help agent")
        root_labels = [str(node.label) for node in tree.root.children]
        for resource in ("OpenAI chat model", "Search FAQ", "Get ticket"):
            assert not any("[미연결]" in label and resource in label for label in root_labels)
            assert sum(node.data == resource for node in descendants(tree.root)) == 1
        tree.select_node(agent)
        await pilot.pause()
        details = app.query_one("#detail-pane", Static).render().plain
        assert "OpenAI chat model" in details
        assert "Search FAQ, Get ticket" in details
        await pilot.press("q")


def test_tui_shows_warnings_on_open():
    asyncio.run(_exercise_broken_tui())


async def _exercise_broken_tui():
    path = Path(__file__).parent / "fixtures/it-agent-broken.json"
    app = TflowApp(load_workflow(path), path)
    async with app.run_test() as pilot:
        warnings = app.query_one("#warnings", Static).render().plain
        assert "⚠ 경고 1개" in warnings
        panel = app.query_one("#warning-panel", Static)
        assert not panel.display
        await pilot.press("w")
        assert panel.display
        assert "없는 연결 대상: Has user? → IT help agnet" in panel.render().plain
        await pilot.press("w")
        assert not panel.display


def test_broken_it_agent_keeps_ai_connections():
    path = Path(__file__).parent / "fixtures/it-agent-broken.json"
    workflow = load_workflow(path)
    assert (len(workflow.nodes), len(workflow.connections)) == (14, 14)
    assert "없는 연결 대상: Has user? → IT help agnet" in workflow.warnings()
    assert workflow.attachments("IT help agent") == {
        "ai_languageModel": ["OpenAI chat model"],
        "ai_tool": ["Search FAQ", "Get ticket"],
    }


def test_flow_mode_branches_rejoin_cycle_and_keyboard(tmp_path):
    async def run():
        names = ("Start", "Decision", "Left", "Right", "Join", "Unused")
        nodes = [{"name": name, "type": "n8n-nodes-base." +
                  ("webhook" if name == "Start" else "if" if name == "Decision" else "set")}
                 for name in names]
        edges = [Connection("Start", "Decision", "main", 0, 0),
                 Connection("Decision", "Left", "main", 0, 0),
                 Connection("Decision", "Right", "main", 1, 0),
                 Connection("Left", "Join", "main", 0, 0),
                 Connection("Right", "Join", "main", 0, 0),
                 Connection("Join", "Decision", "main", 0, 0)]
        app = TflowApp(Workflow("cycle", nodes, edges), tmp_path / "cycle.json")
        async with app.run_test(size=(76, 24)) as pilot:
            await pilot.press("2")
            flow = app.query_one("#box-flow", FlowMap)
            assert flow.display and not app.query_one("#flow-tree", Tree).display
            def descendants(node):
                yield node
                for child in node.children:
                    yield from descendants(child)
            layout = flow.map_layout
            assert len(layout.boxes) == 6
            assert len(layout.cycles) == 1
            assert layout.boxes["Left"].x != layout.boxes["Right"].x
            assert len([name for name in layout.boxes if name == "Join"]) == 1
            drawing = render_flow(layout, app.workflow).plain
            assert "true" in drawing and "false" in drawing and "↩" in drawing
            flow.cursor = flow.map_layout.order.index("Left")
            flow.refresh_map()
            await pilot.press("enter")
            await pilot.pause()
            assert "Left" in app.query_one("#detail-pane", Static).render().plain
            assert not app.screen.has_class("flow-full")
            await pilot.press("tab")
            assert app.query_one("#detail-pane", Static).has_focus
            await pilot.press("1")
            tree = app.query_one("#flow-tree", Tree)
            assert tree.display
            tree_left = next(node for node in descendants(tree.root) if node.data == "Left")
            tree.cursor_line = next(line for line in range(tree.last_line + 1)
                                    if tree.get_node_at_line(line) is tree_left)
            expanded_before = tree_left.is_expanded
            await pilot.press("space")
            assert tree_left.is_expanded != expanded_before
    asyncio.run(run())


def test_detail_display_masks_secret_and_url_query():
    assert _safe_display("Authorization: Bearer private-token") == "[민감정보 숨김]"
    assert _safe_display("URL: https://example.test/path?token=private") == "URL: https://example.test/path?…"
    assert _safe_display("URL: https://example.test/path?search=hello") == "URL: https://example.test/path?…"


def test_assistant_layout_warnings_and_mermaid(tmp_path):
    asyncio.run(_exercise_assistant_layout(tmp_path))


async def _exercise_assistant_layout(tmp_path):
    source = SAMPLES / "assistant.json"
    copy = tmp_path / "assistant.json"
    copy.write_bytes(source.read_bytes())
    workflow = load_workflow(copy)

    async def fake_explainer(context, key):
        return "직원 요청을 여러 업무로 나누는 역할을 합니다."

    descriptions = DescriptionService(DescriptionCache(tmp_path / "cache.json"), fake_explainer, "test-only")
    app = TflowApp(workflow, copy, descriptions)
    async with app.run_test(size=(120, 35)) as pilot:
        assert "TFLOW | Workflow Explorer" in app.query_one("#topbar", Static).render().plain
        assert "노드 28" in app.query_one("#topbar", Static).render().plain
        assert "연결 21" in app.query_one("#topbar", Static).render().plain
        assert "✓ 경고 없음" in app.query_one("#warnings", Static).render().plain
        flow = app.query_one("#box-flow", FlowMap)
        layout = flow.map_layout
        drawing = render_flow(layout, workflow).plain
        assert len(layout.boxes) == 18
        assert len([name for name in layout.boxes if name == "Collect results"]) == 1
        assert all(label in drawing for label in ("it", "meeting", "other", "true", "false"))
        assert "안내 메모" in drawing and "AI 연결" in drawing
        assert app.screen.has_class("flow-full")
        await pilot.press("w")
        panel = app.query_one("#warning-panel", Static)
        assert not panel.display
        tree = app.query_one("#flow-tree", Tree)
        def descendants(node):
            yield node
            for child in node.children:
                yield from descendants(child)
        labels = [str(node.label) for node in descendants(tree.root)]
        assert any("[true]" in label and "Split tasks" in label for label in labels)
        assert any("[false]" in label and "Reject empty" in label for label in labels)
        assert any("재합류" in label and "Collect results" in label for label in labels)
        assert any("미연결" in label for label in labels)
        agent = next(node for node in descendants(tree.root) if node.data == "Split tasks")
        tree.select_node(agent)
        await pilot.pause()
        detail = app.query_one("#detail-pane", Static).render().plain
        for section in ("NODE DETAILS", "CONNECTIONS", "AI EXPLANATION", "하는 일:", "상태: 새로 생성"):
            assert section in detail
        assert detail.index("NODE DETAILS") < detail.index("AI EXPLANATION") < detail.index("CONNECTIONS") < detail.index("INSTRUCTIONS") < detail.index("STATUS")
        tree.select_node(next(node for node in descendants(tree.root) if node.data == "Assistant webhook"))
        tree.select_node(agent)
        await pilot.pause()
        assert "상태: 캐시 사용" in app.query_one("#detail-pane", Static).render().plain
        await pilot.press("m")
        assert copy.with_suffix(".md").read_text() == render_markdown(workflow)
        assert "m Mermaid 저장" in app.query_one("#shortcuts", Static).render().plain
        await pilot.press("q")

    compact = TflowApp(workflow, copy, descriptions)
    async with compact.run_test(size=(76, 24)):
        assert compact.screen.has_class("narrow")
        assert compact._mode == "FLOW"
        assert compact.query_one("#box-flow", FlowMap).display
        assert not compact.query_one("#flow-tree", Tree).display
        assert compact.query_one("#box-flow", FlowMap).size.height > 0
        assert compact.screen.has_class("flow-full")
        assert compact.query_one("#box-flow", FlowMap).scrollable_content_region.width > 0
