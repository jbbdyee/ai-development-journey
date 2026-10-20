"""Interactive tree, flow, and details for a local n8n workflow."""

from pathlib import Path
import os
import re
import textwrap

from rich.text import Text
from textual.binding import Binding
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.widgets import RichLog, Static, Tree
from textual import work

from .details import node_details
from .explanations import DescriptionCache, DescriptionResult, DescriptionService
from .flow_map import FlowLayout, layout_flow, render_flow
from .render import render_markdown
from .translations import SENSITIVE, TranslationResult, TranslationService
from .workflow import Workflow, branch_label


class DetailPane(Static):
    can_focus = True


class FlowMap(RichLog):
    """Focusable, scrollable map; geometry lives in flow_map.py."""

    can_focus = True
    BINDINGS = [("up", "previous", "이전 노드"), ("down", "next", "다음 노드"),
                ("left", "pan_left", "왼쪽"), ("right", "pan_right", "오른쪽"),
                ("enter", "open_details", "상세")]

    def __init__(self, layout: FlowLayout, workflow: Workflow, **kwargs) -> None:
        super().__init__(min_width=layout.width, wrap=False, auto_scroll=False, **kwargs)
        self.map_layout = layout
        self.workflow = workflow
        self.cursor = 0

    @property
    def selected_name(self) -> str | None:
        return self.map_layout.order[self.cursor] if self.map_layout.order else None

    def on_mount(self) -> None:
        self.refresh_map()

    def refresh_map(self) -> None:
        self.clear()
        self.write(render_flow(self.map_layout, self.workflow, self.selected_name))

    def _move(self, delta: int) -> None:
        if not self.map_layout.order:
            return
        self.cursor = min(max(self.cursor + delta, 0), len(self.map_layout.order) - 1)
        self.refresh_map()
        box = self.map_layout.boxes[self.selected_name]
        self.scroll_to(x=max(0, box.x - 3), y=max(0, box.y - 3), animate=False)

    def action_previous(self) -> None:
        self._move(-1)

    def action_next(self) -> None:
        self._move(1)

    def action_pan_left(self) -> None:
        self.scroll_relative(x=-10, animate=False)

    def action_pan_right(self) -> None:
        self.scroll_relative(x=10, animate=False)

    def action_open_details(self) -> None:
        if self.selected_name:
            self.app._select_name(self.selected_name)
            self.app._details_open = True
            self.app._refresh_flow_detail_visibility()


def _safe_display(value: str) -> str:
    lines = []
    for line in value.splitlines():
        if SENSITIVE.search(line):
            lines.append("[민감정보 숨김]")
        else:
            lines.append(re.sub(r"https?://[^\s?]+\?\S+", lambda match: match.group().split("?", 1)[0] + "?…", line))
    return "\n".join(lines)


class TflowApp(App):
    CSS = """
    Screen { background: #0c1422; color: #d9e5f3; }
    #topbar { height: 1; padding: 0 1; background: #172842; color: #eaf2ff; }
    #warnings { height: 1; padding: 0 1; background: #142033; }
    #warning-panel { display: none; height: auto; max-height: 8; padding: 0 1;
                     overflow-y: auto; background: #291c25; color: #ffc5be; }
    #panes { height: 1fr; layout: horizontal; }
    #tree-pane { width: 58%; height: 1fr; border: round #295377; background: #111e31; }
    #detail-pane { width: 42%; height: 1fr; border: round #295377; padding: 0 1;
                   overflow-y: auto; overflow-x: hidden; background: #101b2b; }
    #tree-title { height: 1; padding: 0 1; color: #86c5ff; text-style: bold; }
    #flow-tree { display: none; height: 1fr; background: #111e31; }
    #box-flow { height: 1fr; overflow-x: auto; overflow-y: auto; background: #111e31; }
    #flow-tree > .tree--cursor { background: #285078; color: #ffffff; text-style: bold; }
    #flow-tree:focus > .tree--cursor { background: #3275ad; color: #ffffff; text-style: bold; }
    Screen.flow-full #tree-pane { width: 100%; }
    Screen.flow-full #detail-pane { display: none; }
    #shortcuts { height: 1; padding: 0 1; background: #172842; color: #b7c9df; }
    Screen.narrow #panes { layout: vertical; }
    Screen.narrow #tree-pane { width: 100%; height: 58%; }
    Screen.narrow #detail-pane { width: 100%; height: 42%; }
    """
    BINDINGS = [("q", "quit", "종료"), ("m", "save_md", "Mermaid 저장"),
                ("1", "tree_mode", "TREE"), ("2", "flow_mode", "FLOW"),
                ("tab", "next_panel", "패널 이동"),
                ("escape", "close_details", "상세 닫기"),
                Binding("space", "toggle_node", "노드 접기/펼치기", priority=True),
                ("w", "toggle_warnings", "경고 보기"),
                ("e", "toggle_instruction_language", "지시문 언어"),
                ("v", "toggle_instruction_expansion", "영어 원문 펼치기")]

    def __init__(self, workflow: Workflow, source: Path, descriptions: DescriptionService | None = None,
                 translations: TranslationService | None = None, initial_mode: str = "FLOW") -> None:
        super().__init__()
        self.workflow = workflow
        self.source = source
        cache_dir = Path(os.environ.get("TFLOW_CACHE_DIR") or Path.cwd() / ".tflow-cache")
        self.descriptions = descriptions or DescriptionService(
            DescriptionCache(cache_dir / "descriptions.json")
        )
        self.translations = translations or TranslationService(
            DescriptionCache(cache_dir / "translations.json")
        )
        self._selected_name: str | None = None
        self._description_result: DescriptionResult | None = None
        self._translation_result: TranslationResult | None = None
        self._show_english = False
        self._english_expanded = False
        self._warnings = workflow.warnings()
        self._layout = layout_flow(workflow)
        self._details_open = False
        if initial_mode not in ("TREE", "FLOW"):
            raise ValueError("initial_mode must be TREE or FLOW")
        self._mode = initial_mode

    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        yield Static(Text(f"⚠ 경고 {len(self._warnings)}개  ·  w로 내용 보기" if self._warnings else "✓ 경고 없음"), id="warnings")
        yield Static(Text("\n".join(f"• {warning}" for warning in self._warnings)), id="warning-panel")
        with Horizontal(id="panes"):
            with Vertical(id="tree-pane"):
                yield Static(f"WORKFLOW {self._mode}", id="tree-title")
                yield Tree(Text(self.workflow.name), id="flow-tree")
                yield FlowMap(self._layout, self.workflow, id="box-flow")
            yield DetailPane(Text("NODE DETAILS\n\n왼쪽에서 노드를 선택하세요."), id="detail-pane")
        yield Static(id="shortcuts")

    def _update_topbar(self, width: int) -> None:
        prefix = "TFLOW | Workflow Explorer  ·  "
        suffix = (f"  ·  노드 {len(self.workflow.nodes)}  ·  "
                  f"연결 {len(self.workflow.connections)}  ·  경고 {len(self._warnings)}")
        name = Text(self.workflow.name)
        name.truncate(max(4, width - len(prefix) - len(suffix) - 2), overflow="ellipsis")
        title = Text(prefix, style="bold #83d5ff")
        title.append(name)
        title.append(suffix, style="#afc5dc")
        title.truncate(max(8, width - 2), overflow="ellipsis")
        self.query_one("#topbar", Static).update(title)

    def on_resize(self, event: Resize) -> None:
        self.screen.set_class(event.size.width < 88, "narrow")
        self._update_topbar(event.size.width)
        self._update_shortcuts(event.size.width)
        if self._selected_name:
            self._redraw_detail()

    def _update_shortcuts(self, width: int) -> None:
        full = "1 TREE  2 FLOW  Tab 패널  ↑↓ 이동  Enter 선택  Space TREE 접기  e 언어  v 펼치기  w 경고  m Mermaid 저장  q 종료"
        compact = "1 TREE  2 FLOW  Tab 패널  ↑↓  Enter 상세  Esc 닫기  e  v  w  m  q"
        self.query_one("#shortcuts", Static).update(full if width >= 120 else compact)

    @staticmethod
    def _node_label(workflow: Workflow, name: str, branch: str | None = None,
                    repeated: bool = False) -> Text:
        node = workflow.by_name.get(name)
        kind = node["type"].rsplit(".", 1)[-1] if node else "missing"
        icon, color = {
            "webhook": ("◆", "#45d4cc"),
            "agent": ("●", "#73aaff"),
            "if": ("◇", "#f6d36c"),
            "switch": ("◇", "#f6d36c"),
            "lmChatOpenAi": ("◆", "#c69bff"),
            "httpRequestTool": ("◆", "#c69bff"),
            "missing": ("!", "#ff7777"),
        }.get(kind, ("·", "#b8cbe0"))
        label = Text()
        if branch:
            label.append(f"[{branch}] ", style="#f6d36c bold")
        label.append(f"{icon} {name}", style=color)
        if repeated:
            label.append("  ↩ 재합류", style="#8296af")
        return label

    def _instruction_source(self, name: str) -> str:
        node = self.workflow.by_name[name]
        if not node["type"].endswith(".agent"):
            return ""
        return str((node.get("parameters") or {}).get("options", {}).get("systemMessage") or "")

    def _instruction_view(self, source: str) -> tuple[str, str]:
        result = self._translation_result
        translated = bool(result and result.text and not self._show_english)
        body_source = result.text if translated and result else source
        language = "한국어 번역" if translated else "영어 원문"

        width = max(24, self.query_one("#detail-pane", Static).size.width - 6)
        lines = []
        for line in _safe_display(body_source).splitlines() or [body_source]:
            lines.extend(textwrap.wrap(line, width=width, break_long_words=False,
                                       break_on_hyphens=False) or [""])
        collapsed = len(lines) > 4 and not self._english_expanded
        shown = lines[:4] if collapsed else lines
        status = result.status if result else "번역 중"
        suffix = ("\n… v로 영어 원문 펼치기" if not translated else "\n… v로 한국어 번역 펼치기") if collapsed else ("\nv로 접기" if len(lines) > 4 else "")
        body = "\n".join(shown)
        return f"지시문: {language}\n{body}{suffix}", status

    def _detail_text(self, name: str, result: DescriptionResult | None = None) -> Text:
        raw = node_details(self.workflow, name).splitlines()
        source = self._instruction_source(name)
        settings = ([] if source else
                    [line for line in raw[2:] if not line.startswith(("모델:", "Tool:"))])
        attached = self.workflow.attachments(name)
        incoming = [edge.source for edge in self.workflow.main if edge.target == name]
        outgoing = [edge.target for edge in self.workflow.main if edge.source == name]
        detail = Text()
        detail.append("NODE DETAILS\n", style="#80c8ff bold")
        detail.append(f"{raw[0]}\n", style="bold #f1f6ff")
        detail.append(f"종류: {raw[1].removeprefix('종류: ')}\n", style="#b5c9dc")
        if not source:
            detail.append(_safe_display("\n".join(settings)) if settings else "주요 설정 없음", style="#d9e5f3")
        detail.append("\n\nAI EXPLANATION\n", style="#c69bff bold")
        if result is None:
            detail.append("하는 일: 설명 생성 중…\n상태: 생성 중", style="#f6d36c")
        else:
            explanation = result.text or result.status
            detail.append(f"하는 일: {explanation}\n상태: {result.status}",
                          style="#d9e5f3" if result.text else "#f6d36c")
        detail.append("\n\nCONNECTIONS\n", style="#80c8ff bold")
        detail.append("앞: " + (", ".join(incoming) or "없음") + "\n")
        detail.append("뒤: " + (", ".join(outgoing) or "없음") + "\n")
        branches = [f"{branch_label(self.workflow, edge)} → {edge.target}"
                    for edge in self.workflow.outgoing(name) if branch_label(self.workflow, edge)]
        if branches:
            detail.append("분기: " + ", ".join(branches) + "\n")
        detail.append("모델: " + (", ".join(attached["ai_languageModel"]) or "없음") + "\n")
        detail.append("Tool: " + (", ".join(attached["ai_tool"]) or "없음"))
        if source:
            instruction, translation_status = self._instruction_view(source)
            detail.append("\n\nINSTRUCTIONS\n", style="#80c8ff bold")
            detail.append(instruction, style="#d9e5f3")
            detail.append("\n\nSTATUS\n", style="#80c8ff bold")
            detail.append(f"번역 상태: {translation_status}\n", style="#74d6a6" if translation_status == "캐시 사용" else "#f6d36c")
            detail.append(f"설명 상태: {result.status if result else '생성 중'}")
        return detail

    def _redraw_detail(self) -> None:
        if self._selected_name:
            self.query_one("#detail-pane", Static).update(
                self._detail_text(self._selected_name, self._description_result)
            )

    def _protected_terms(self, source: str) -> tuple[str, ...]:
        return tuple(name for name in self.workflow.by_name if name in source)

    def on_mount(self) -> None:
        self._update_topbar(self.size.width)
        self._update_shortcuts(self.size.width)
        self.screen.set_class(self.size.width < 88, "narrow")
        self._populate(self.query_one("#flow-tree", Tree), False)
        self._set_mode(self._mode)

    def _populate(self, tree: Tree, boxed: bool) -> None:
        seen: set[str] = set()

        def add(parent, name: str, label: str | None = None) -> None:
            repeated = name in seen
            title = (self._box_label if boxed else self._node_label)(self.workflow, name, label, repeated)
            entry = parent.add(title, data=name if name in self.workflow.by_name else None)
            if repeated or name not in self.workflow.by_name:
                return
            seen.add(name)
            for edge in self.workflow.outgoing(name):
                add(entry, edge.target, branch_label(self.workflow, edge))
            attached = self.workflow.attachments(name)
            for kind, title in (("ai_languageModel", "모델"), ("ai_tool", "Tool")):
                for resource in attached[kind]:
                    resource_label = (self._box_label(self.workflow, resource, title) if boxed else
                                      Text(f"◆ {title} {resource}", style="#c69bff"))
                    entry.add_leaf(resource_label, data=resource)
                    if resource in self.workflow.by_name:
                        seen.add(resource)
            entry.expand()

        for start in self.workflow.starts():
            if start not in seen:
                add(tree.root, start)
        disconnected = [node["name"] for node in self.workflow.nodes if node["name"] not in seen]
        if disconnected:
            group = tree.root.add(Text(f"미연결 · {len(disconnected)}", style="#ff9a85 bold"))
            for name in disconnected:
                if name not in seen:
                    add(group, name)
            group.expand()
        tree.root.expand()
        tree.show_root = False

    def action_tree_mode(self) -> None:
        self._set_mode("TREE")

    def action_flow_mode(self) -> None:
        self._set_mode("FLOW")

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        self.query_one("#flow-tree", Tree).display = mode == "TREE"
        self.query_one("#box-flow", FlowMap).display = mode == "FLOW"
        self.query_one("#tree-title", Static).update(
            "WORKFLOW TREE  ·  Space 접기/펼치기" if mode == "TREE" else
            "WORKFLOW FLOW  ·  위→아래  ·  ↩ 순환 참조"
        )
        self._refresh_flow_detail_visibility()
        self.query_one("#flow-tree", Tree).focus() if mode == "TREE" else self.query_one("#box-flow", FlowMap).focus()

    def _refresh_flow_detail_visibility(self) -> None:
        self.screen.set_class(self._mode == "FLOW" and not self._details_open, "flow-full")

    def action_close_details(self) -> None:
        if self._mode == "FLOW":
            self._details_open = False
            self._refresh_flow_detail_visibility()
            self.query_one("#box-flow", FlowMap).focus()

    def action_next_panel(self) -> None:
        detail = self.query_one("#detail-pane", Static)
        if self._mode == "FLOW" and not self._details_open:
            self._details_open = True
            self._refresh_flow_detail_visibility()
        tree = self.query_one("#flow-tree", Tree) if self._mode == "TREE" else self.query_one("#box-flow", FlowMap)
        (tree if detail.has_focus else detail).focus()

    def action_toggle_node(self) -> None:
        if self._mode != "TREE":
            return
        tree = self.query_one("#flow-tree", Tree)
        node = tree.cursor_node
        if node and node.children:
            node.toggle()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        name = event.node.data
        if name in self.workflow.by_name:
            self._select_name(name)

    def _select_name(self, name: str) -> None:
        self._selected_name = name
        self._description_result = None
        self._translation_result = None
        self._show_english = False
        self._english_expanded = False
        self._redraw_detail()
        self._show_description(name)
        source = self._instruction_source(name)
        if source:
            self._show_translation(name, source)

    @work(exclusive=True)
    async def _show_description(self, name: str) -> None:
        result = await self.descriptions.describe(self.workflow, name)
        if self._selected_name != name:
            return
        self._description_result = result
        self._redraw_detail()

    @work(exclusive=True, group="translation")
    async def _show_translation(self, name: str, source: str) -> None:
        result = await self.translations.translate(source, self._protected_terms(source))
        if self._selected_name != name or self._instruction_source(name) != source:
            return
        self._translation_result = result
        self._redraw_detail()

    def action_toggle_instruction_language(self) -> None:
        if self._selected_name and self._instruction_source(self._selected_name):
            self._show_english = not self._show_english
            self._redraw_detail()

    def action_toggle_instruction_expansion(self) -> None:
        if self._selected_name and self._instruction_source(self._selected_name):
            self._english_expanded = not self._english_expanded
            self._redraw_detail()

    def action_toggle_warnings(self) -> None:
        if self._warnings:
            panel = self.query_one("#warning-panel", Static)
            panel.display = not panel.display

    def action_save_md(self) -> None:
        output = self.source.with_suffix(".md")
        try:
            output.write_text(render_markdown(self.workflow), encoding="utf-8")
        except OSError as error:
            self.notify(str(error), severity="error")
        else:
            self.notify(f"저장: {output}")
