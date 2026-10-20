"""Plain text and Mermaid renderers."""

from html import escape

from .workflow import Workflow, branch_label


def render_tree(workflow: Workflow) -> str:
    lines = [f"{workflow.name} · 노드 {len(workflow.nodes)} · 연결 {len(workflow.connections)}"]
    seen: set[str] = set()

    def visit(name: str, line_prefix: str = "", children_prefix: str = "") -> None:
        repeated = name in seen
        lines.append(f"{line_prefix}{name}" + (" (다시 합류/반복)" if repeated else ""))
        if repeated or name not in workflow.by_name:
            return
        seen.add(name)
        edges = workflow.outgoing(name)
        for i, edge in enumerate(edges):
            last = i == len(edges) - 1
            branch = branch_label(workflow, edge)
            connector = "└─ " if last else "├─ "
            label = f"[{branch}] " if branch else ""
            visit(edge.target, children_prefix + connector + label,
                  children_prefix + ("   " if last else "│  "))

    for start in workflow.starts():
        if start not in seen:
            visit(start)
    if not seen:
        lines.append("(시작 노드 없음)")
    return "\n".join(lines)


def _mermaid_label(value: str) -> str:
    return escape(value, quote=True).replace("\n", "<br/>").replace("`", "&#96;")


def render_mermaid(workflow: Workflow) -> str:
    ids = {node["name"]: f"n{i}" for i, node in enumerate(workflow.nodes)}
    lines = ["flowchart TD"]
    for name, node_id in ids.items():
        lines.append(f'  {node_id}["{_mermaid_label(name)}"]')
    for edge in workflow.main:
        if edge.source not in ids or edge.target not in ids:
            continue
        label = branch_label(workflow, edge)
        arrow = f' -->|"{_mermaid_label(label)}"|' if label else " -->"
        lines.append(f"  {ids[edge.source]}{arrow} {ids[edge.target]}")
    return "\n".join(lines)


def render_markdown(workflow: Workflow) -> str:
    title = workflow.name.replace("\n", " ")
    return (f"# {title}\n\n"
            f"- 노드: {len(workflow.nodes)}\n"
            f"- 연결: {len(workflow.connections)}\n\n"
            f"```mermaid\n{render_mermaid(workflow)}\n```\n")
