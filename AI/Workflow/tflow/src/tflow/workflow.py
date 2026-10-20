"""Shared n8n parser for text, Markdown, and a future TUI."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Connection:
    source: str
    target: str
    kind: str
    output: int
    input: int


@dataclass
class Workflow:
    name: str
    nodes: list[dict[str, Any]]
    connections: list[Connection]

    @property
    def by_name(self) -> dict[str, dict[str, Any]]:
        return {node["name"]: node for node in self.nodes}

    @property
    def main(self) -> list[Connection]:
        return [edge for edge in self.connections if edge.kind == "main"]

    def outgoing(self, name: str) -> list[Connection]:
        return [edge for edge in self.main if edge.source == name]

    def attachments(self, name: str) -> dict[str, list[str]]:
        """AI resource nodes point *to* the Agent, unlike main flow edges."""
        return {
            kind: [edge.source for edge in self.connections
                   if edge.kind == kind and edge.target == name]
            for kind in ("ai_languageModel", "ai_tool")
        }

    def warnings(self) -> list[str]:
        by_name = self.by_name
        names = set(by_name)
        warnings: list[str] = []
        incident: set[str] = set()
        for edge in self.connections:
            if edge.source not in names:
                warnings.append(f"없는 출발 노드: {edge.source} → {edge.target}")
            else:
                incident.add(edge.source)
            if edge.target not in names:
                warnings.append(f"없는 연결 대상: {edge.source} → {edge.target}")
            else:
                incident.add(edge.target)
            source = by_name.get(edge.source)
            if source and edge.kind == "main":
                kind = source["type"].rsplit(".", 1)[-1]
                if kind == "if" and edge.output not in (0, 1):
                    warnings.append(f"잘못된 분기: {edge.source} 출력 {edge.output}")
                elif kind == "switch":
                    rules = (source.get("parameters") or {}).get("rules") or {}
                    count = len(rules.get("values") or [])
                    if count and edge.output > count:
                        warnings.append(f"잘못된 분기: {edge.source} 출력 {edge.output}")
        for node in self.nodes:
            if node["name"] not in incident and not node["type"].endswith(".stickyNote"):
                warnings.append(f"고립된 노드: {node['name']}")
        return warnings

    def starts(self) -> list[str]:
        webhooks = [node["name"] for node in self.nodes if node["type"].endswith(".webhook")]
        if webhooks:
            return webhooks
        incoming = {edge.target for edge in self.main}
        return [node["name"] for node in self.nodes if node["name"] not in incoming]


def load_workflow(path: str | Path) -> Workflow:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    nodes = data["nodes"]
    if not isinstance(nodes, list) or not isinstance(data["connections"], dict):
        raise ValueError("nodes는 목록, connections는 객체여야 합니다")
    names = [node["name"] for node in nodes]
    if len(names) != len(set(names)):
        raise ValueError("노드 이름이 중복됩니다")
    edges = [
        Connection(source, item["node"], kind, output, item.get("index", 0))
        for source, kinds in data["connections"].items()
        for kind, groups in kinds.items()
        for output, group in enumerate(groups)
        for item in group
    ]
    return Workflow(data.get("name") or Path(path).stem, nodes, edges)


def branch_label(workflow: Workflow, edge: Connection) -> str | None:
    source = workflow.by_name.get(edge.source)
    if source is None:
        return None
    kind = source["type"].rsplit(".", 1)[-1]
    if kind == "if":
        return "true" if edge.output == 0 else "false" if edge.output == 1 else str(edge.output)
    if kind == "switch":
        rules = source.get("parameters", {}).get("rules", {}).get("values", [])
        if edge.output < len(rules):
            label = rules[edge.output].get("outputKey")
            if label:
                return str(label)
        return f"output {edge.output}"
    return None
