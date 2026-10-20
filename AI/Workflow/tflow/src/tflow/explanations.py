"""Safe LLM context, persistent description cache, and OpenAI adapter."""

import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Awaitable, Callable
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, urlunsplit

from .workflow import Workflow, branch_label


MODEL = "gpt-4.1-mini"
CACHE_VERSION = 1
REDACTED = "[가림]"
SECRET_WORDS = re.compile(
    r"(?i)(authorization|credential|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
    r"bearer|password|passwd|secret|private[_ -]?key|client[_ -]?secret|x-api-key|sk-[A-Za-z0-9])"
)
SECRET_KEYS = re.compile(r"(?i)(credential|auth|header|token|password|secret|key)")


def _safe_text(value: Any, limit: int = 500) -> str:
    text = str(value)
    if SECRET_WORDS.search(text):
        return REDACTED
    return text[:limit]


def _safe_url(value: Any) -> str:
    text = str(value)
    if text.startswith("={{") or SECRET_WORDS.search(text):
        return REDACTED
    try:
        parts = urlsplit(text)
        host = parts.hostname or ""
        if not host:
            return REDACTED
        path = _safe_text(parts.path, 180)
        return urlunsplit((parts.scheme, host, path, "", ""))
    except ValueError:
        return REDACTED


def _settings(node: dict[str, Any]) -> dict[str, Any]:
    kind = node["type"].rsplit(".", 1)[-1]
    params = node.get("parameters") or {}
    result: dict[str, Any] = {}
    if kind == "webhook":
        result = {"method": _safe_text(params.get("httpMethod", "GET")),
                  "path": _safe_text(params.get("path", ""))}
    elif kind in ("httpRequest", "httpRequestTool"):
        result = {"method": _safe_text(params.get("method", "GET")),
                  "url": _safe_url(params.get("url", ""))}
    elif kind == "agent":
        message = (params.get("options") or {}).get("systemMessage", "")
        result = {"instruction": _safe_text(message)}
    elif kind == "code":
        # Source code can contain arbitrary literals, so never send it to the API.
        result = {"code_present": bool(params.get("jsCode") or params.get("pythonCode"))}
    elif kind == "if":
        conditions = params.get("conditions") or {}
        selected = []
        for group in ("conditions", "string", "number", "boolean", "dateTime"):
            for condition in conditions.get(group, []):
                selected.append({
                    "left": _safe_text(condition.get("leftValue", condition.get("value1", ""))),
                    "operator": _safe_text((condition.get("operator") or {}).get("operation", "")),
                    "right": _safe_text(condition.get("rightValue", condition.get("value2", ""))),
                })
        result = {"conditions": selected[:8]}
    elif kind == "switch":
        result = {"outputs": [_safe_text(rule.get("outputKey", i))
                              for i, rule in enumerate((params.get("rules") or {}).get("values", []))]}
    elif kind == "lmChatOpenAi":
        model = params.get("model") or {}
        result = {"model": _safe_text(model.get("value", "") if isinstance(model, dict) else model)}
    return {key: value for key, value in result.items() if not SECRET_KEYS.search(key)}


def safe_context(workflow: Workflow, name: str) -> dict[str, Any]:
    node = workflow.by_name[name]
    incoming = [{"from": _safe_text(edge.source), "kind": _safe_text(edge.kind),
                 "output": _safe_text(branch_label(workflow, edge) or edge.output)}
                for edge in workflow.connections if edge.target == name]
    outgoing = [{"to": _safe_text(edge.target), "kind": _safe_text(edge.kind),
                 "output": _safe_text(branch_label(workflow, edge) or edge.output)}
                for edge in workflow.connections if edge.source == name]
    attached = workflow.attachments(name)
    return {
        "workflow": _safe_text(workflow.name),
        "node": _safe_text(name),
        "type": _safe_text(node["type"]),
        "settings": _settings(node),
        "incoming": incoming,
        "outgoing": outgoing,
        "model_nodes": [_safe_text(item) for item in attached["ai_languageModel"]],
        "tool_nodes": [_safe_text(item) for item in attached["ai_tool"]],
    }


def cache_key(context: dict[str, Any]) -> str:
    payload = json.dumps({"version": CACHE_VERSION, "model": MODEL, "context": context},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DescriptionCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.data = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.data = {}

    def get(self, key: str) -> str | None:
        value = self.data.get(key)
        return value if isinstance(value, str) else None

    def put(self, key: str, value: str) -> None:
        updated = {**self.data, key: value}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.path)
        self.data = updated


async def openai_chat(system: str, user: str, api_key: str) -> str:
    """Shared Chat Completions transport; never logs request data or errors."""
    def request() -> str:
        body = json.dumps({
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }).encode("utf-8")
        req = Request("https://api.openai.com/v1/chat/completions", data=body,
                      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        with urlopen(req, timeout=20) as response:
            result = json.load(response)
        return result["choices"][0]["message"]["content"].strip()

    return await asyncio.to_thread(request)


async def openai_explainer(context: dict[str, Any], api_key: str) -> str:
    return await openai_chat(
        "당신은 n8n 워크플로우를 설명합니다. 제공된 구조만 근거로 이 노드가 이 워크플로우에서 하는 일을 한국어 1~2문장으로 설명하세요. 비밀값은 추측하거나 출력하지 마세요.",
        json.dumps(context, ensure_ascii=False), api_key,
    )


@dataclass(frozen=True)
class DescriptionResult:
    text: str | None
    status: str


class DescriptionService:
    def __init__(self, cache: DescriptionCache, explainer: Callable[[dict[str, Any], str], Awaitable[str]] = openai_explainer,
                 api_key: str | None = None) -> None:
        self.cache = cache
        self.explainer = explainer
        self.api_key = os.environ.get("OPENAI_API_KEY", "") if api_key is None else api_key
        self._lock = asyncio.Lock()

    async def describe(self, workflow: Workflow, name: str) -> DescriptionResult:
        context = safe_context(workflow, name)
        key = cache_key(context)
        cached = self.cache.get(key)
        if cached:
            return DescriptionResult(cached, "캐시 사용")
        if not self.api_key:
            return DescriptionResult(None, "API 키 미설정")
        async with self._lock:
            cached = self.cache.get(key)
            if cached:
                return DescriptionResult(cached, "캐시 사용")
            try:
                answer = (await self.explainer(context, self.api_key)).strip()
                if not answer or SECRET_WORDS.search(answer):
                    raise ValueError("unsafe or empty response")
                self.cache.put(key, answer)
            except Exception:
                # Do not print HTTP exceptions: they can include request details.
                return DescriptionResult(None, "설명 생성 실패")
            return DescriptionResult(answer, "새로 생성")
