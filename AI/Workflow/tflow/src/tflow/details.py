"""Readable, credential-free node summaries for the TUI."""

import json
from typing import Any

from .workflow import Workflow


def _short(value: Any, limit: int = 700) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    return value[:limit] + ("…" if len(value) > limit else "")


def node_details(workflow: Workflow, name: str) -> str:
    node = workflow.by_name[name]
    kind = node["type"].rsplit(".", 1)[-1]
    params = node.get("parameters") or {}
    lines = [name, f"종류: {kind}"]

    if kind == "webhook":
        lines += [f"방식: {params.get('httpMethod', 'GET')}",
                  f"경로: /{str(params.get('path', '')).lstrip('/')}"]
    elif kind in ("httpRequest", "httpRequestTool"):
        lines += [f"방식: {params.get('method', 'GET')}",
                  f"URL: {_short(params.get('url', ''), 300)}"]
    elif kind == "agent":
        message = (params.get("options") or {}).get("systemMessage")
        if message:
            lines.append(f"지시문: {_short(message)}")
        attached = workflow.attachments(name)
        lines.append("모델: " + (", ".join(attached["ai_languageModel"]) or "없음"))
        lines.append("Tool: " + (", ".join(attached["ai_tool"]) or "없음"))
    elif kind == "code":
        code = params.get("jsCode") or params.get("pythonCode") or ""
        lines.append("코드:\n" + "\n".join(str(code).splitlines()[:8])[:700])
    elif kind == "if":
        conditions = params.get("conditions") or {}
        for group in ("conditions", "string", "number", "boolean", "dateTime"):
            for condition in conditions.get(group, []):
                operator = condition.get("operator", "")
                lines.append(f"조건: {_short(condition.get('leftValue', condition.get('value1', '')), 180)} "
                             f"{_short(operator, 180)} "
                             f"{_short(condition.get('rightValue', condition.get('value2', '')), 180)}")
        if len(lines) == 2:
            lines.append(f"조건: {_short(conditions)}")
    elif kind == "switch":
        for i, rule in enumerate((params.get("rules") or {}).get("values", [])):
            lines.append(f"출력 {i}: {rule.get('outputKey') or i}")
    elif kind == "lmChatOpenAi":
        lines.append(f"모델: {_short(params.get('model', ''), 200)}")

    return "\n".join(lines)
