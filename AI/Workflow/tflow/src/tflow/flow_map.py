"""Two-dimensional terminal layout and rendering for n8n main-flow edges."""

from collections import defaultdict, deque
from dataclasses import dataclass

from rich.cells import cell_len
from rich.text import Text

from .workflow import Connection, Workflow, branch_label


BOX_WIDTH = 25
BOX_HEIGHT = 3
X_STEP = 35
Y_STEP = 10
MARGIN = 3


@dataclass(frozen=True)
class Box:
    name: str
    x: int
    y: int
    kind: str


@dataclass
class FlowLayout:
    boxes: dict[str, Box]
    edges: list[Connection]
    cycles: list[Connection]
    notes: list[str]
    resources: list[tuple[str, str, str]]
    order: list[str]
    width: int
    height: int


def layout_flow(workflow: Workflow) -> FlowLayout:
    """Place each reachable execution node once; remove back edges for layering."""
    by_name = workflow.by_name
    executable = {name for name, node in by_name.items()
                  if not node["type"].endswith(".stickyNote")}
    outgoing: dict[str, list[Connection]] = defaultdict(list)
    for edge in workflow.main:
        if edge.source in executable and edge.target in executable:
            outgoing[edge.source].append(edge)

    state: dict[str, int] = {}
    order: list[str] = []
    edges: list[Connection] = []
    cycles: list[Connection] = []

    def visit(name: str) -> None:
        state[name] = 1
        order.append(name)
        for edge in outgoing[name]:
            if state.get(edge.target) == 1:
                cycles.append(edge)
            else:
                edges.append(edge)
                if not state.get(edge.target):
                    visit(edge.target)
        state[name] = 2

    for name in workflow.starts():
        if name in executable and not state.get(name):
            visit(name)
    for name in by_name:
        if name in executable and not state.get(name):
            visit(name)

    # AI resources have their own area, not a lane in the main execution graph.
    attached_names = {edge.source for edge in workflow.connections
                      if edge.kind in ("ai_languageModel", "ai_tool")}
    main_names = {edge.source for edge in edges + cycles} | {edge.target for edge in edges + cycles}
    execution = [name for name in order if name not in attached_names or name in main_names]
    resources = [(edge.target, "모델" if edge.kind == "ai_languageModel" else "Tool", edge.source)
                 for edge in workflow.connections
                 if edge.kind in ("ai_languageModel", "ai_tool") and edge.target in by_name]

    predecessors: dict[str, list[str]] = defaultdict(list)
    successors: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.source in execution and edge.target in execution:
            predecessors[edge.target].append(edge.source)
            successors[edge.source].append(edge.target)
    indegree = {name: len(predecessors[name]) for name in execution}
    ready = deque(name for name in execution if indegree[name] == 0)
    level = {name: 0 for name in execution}
    while ready:
        name = ready.popleft()
        for target in successors[name]:
            level[target] = max(level[target], level[name] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)

    layers: dict[int, list[str]] = defaultdict(list)
    for name in execution:
        layers[level[name]].append(name)
    max_count = max((len(items) for items in layers.values()), default=1)
    boxes: dict[str, Box] = {}
    for depth, names in layers.items():
        offset = (max_count - len(names)) * X_STEP // 2
        for index, name in enumerate(names):
            kind = by_name[name]["type"].rsplit(".", 1)[-1]
            boxes[name] = Box(name, MARGIN + offset + index * X_STEP,
                              MARGIN + depth * Y_STEP, kind)
    drawn = [edge for edge in edges if edge.source in boxes and edge.target in boxes]
    looped = [edge for edge in cycles if edge.source in boxes and edge.target in boxes]
    width = MARGIN * 2 + max_count * X_STEP + 6 + len(looped) * 3
    height = MARGIN * 2 + (max(level.values(), default=0) + 1) * Y_STEP
    notes = [name for name, node in by_name.items() if node["type"].endswith(".stickyNote")]
    return FlowLayout(boxes, drawn, looped, notes, resources,
                      sorted(boxes, key=lambda name: (boxes[name].y, boxes[name].x)), width, height)


def render_flow(layout: FlowLayout, workflow: Workflow, selected: str | None = None) -> Text:
    """Draw edges in gutters first, then boxes, so no edge crosses a label."""
    width = max(layout.width, 40)
    height = layout.height + (3 if layout.resources else 0) + len(layout.resources)
    height += (2 + len(layout.notes)) if layout.notes else 0
    cells = [[" " for _ in range(width)] for _ in range(height)]
    styles: dict[int, list[tuple[int, int, str]]] = defaultdict(list)

    def put(x: int, y: int, value: str) -> None:
        if 0 <= y < height:
            cursor = x
            for character in value:
                span = max(1, cell_len(character))
                if 0 <= cursor < width:
                    cells[y][cursor] = character
                    for extra in range(1, span):
                        if cursor + extra < width:
                            cells[y][cursor + extra] = ""
                cursor += span

    def horizontal(x1: int, x2: int, y: int) -> None:
        for x in range(min(x1, x2), max(x1, x2) + 1):
            old = cells[y][x]
            put(x, y, "─" if old in (" ", "─") else "┼")

    def vertical(x: int, y1: int, y2: int) -> None:
        for y in range(min(y1, y2), max(y1, y2) + 1):
            old = cells[y][x]
            put(x, y, "│" if old in (" ", "│") else "┼")

    for edge in layout.edges:
        source, target = layout.boxes[edge.source], layout.boxes[edge.target]
        sx, tx = source.x + BOX_WIDTH // 2, target.x + BOX_WIDTH // 2
        sy, ty = source.y + BOX_HEIGHT, target.y - 1
        if target.y - source.y == Y_STEP:
            gutter = source.y + BOX_HEIGHT + 2 + min(edge.output, 2)
            vertical(sx, sy, gutter)
            if sx != tx:
                horizontal(sx, tx, gutter)
            vertical(tx, gutter, ty)
            put(tx, ty, "▼")
        else:
            # A long edge runs down the outside gutter, never through later boxes.
            outer = width - 4
            horizontal(sx, outer, sy)
            vertical(outer, sy, ty)
            horizontal(tx, outer, ty)
            put(tx, ty, "▼")

    for index, edge in enumerate(layout.cycles):
        source, target = layout.boxes[edge.source], layout.boxes[edge.target]
        outer = width - 5 - index * 3
        sy, ty = source.y + BOX_HEIGHT + 1, target.y - 1
        horizontal(source.x + BOX_WIDTH // 2, outer, sy)
        vertical(outer, sy, ty)
        horizontal(target.x + BOX_WIDTH // 2, outer, ty)
        put(target.x + BOX_WIDTH // 2, ty, "↩")

    for edge in layout.edges:
        label = branch_label(workflow, edge)
        if label:
            target = layout.boxes[edge.target]
            put(target.x + 1, target.y - 2, str(label)[:12])

    colors = {"webhook": "#45d4cc", "agent": "#c69bff", "if": "#f6d36c",
              "switch": "#f6d36c", "lmChatOpenAi": "#c69bff"}
    for name, box in layout.boxes.items():
        x, y = box.x, box.y
        color = "bold #ffffff on #285078" if name == selected else colors.get(box.kind, "#b8cbe0")
        label = Text(name)
        label.truncate(BOX_WIDTH - 4, overflow="ellipsis")
        title = label.plain + " " * max(0, BOX_WIDTH - 4 - cell_len(label.plain))
        put(x, y, "┌" + "─" * (BOX_WIDTH - 2) + "┐")
        put(x, y + 1, "│ " + title + " │")
        put(x, y + 2, "└" + "─" * (BOX_WIDTH - 2) + "┘")
        for row in (y, y + 1, y + 2):
            styles[row].append((x, x + BOX_WIDTH, color))

    tail = layout.height
    if layout.resources:
        put(MARGIN, tail, "AI 연결 (실행선과 별도)")
        for index, (agent, kind, resource) in enumerate(layout.resources, 1):
            put(MARGIN, tail + index, f"◇ {agent} · {kind}: {resource}"[:width - MARGIN])
        tail += len(layout.resources) + 3
    if layout.notes:
        put(MARGIN, tail, "안내 메모 (실행 흐름 제외)")
        for index, name in enumerate(layout.notes, 1):
            put(MARGIN, tail + index, f"▤ {name}"[:width - MARGIN])

    result = Text(no_wrap=True, overflow="ignore")
    for y, row in enumerate(cells):
        line = Text("".join(row).rstrip(), no_wrap=True)
        for start, end, style in styles[y]:
            line.stylize(style, start, end)
        result.append_text(line)
        if y < len(cells) - 1:
            result.append("\n")
    return result
