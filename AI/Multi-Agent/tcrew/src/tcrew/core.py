"""Configuration and sequential role execution; independent of the LLM provider."""

import re
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Callable, Protocol

import yaml


@dataclass(frozen=True)
class Role:
    name: str
    instruction: str
    inputs: tuple[str, ...]
    kind: str = "step"


@dataclass(frozen=True)
class Config:
    model: str
    roles: tuple[Role, ...]
    max_revisions: int


@dataclass(frozen=True)
class RoleResult:
    name: str
    input: str
    output: str
    duration_seconds: float
    attempt: int = 1
    decision: str | None = None
    reviewer_decision: str | None = None
    validation_feedback: str | None = None


@dataclass(frozen=True)
class RunResult:
    results: tuple[RoleResult, ...]
    revisions: int
    status: str
    reason: str | None = None


class LLM(Protocol):
    def complete(self, *, model: str, role: str, instruction: str, prompt: str) -> str: ...


def load_config(path: Path) -> Config:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"설정을 읽을 수 없습니다: {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("model"), str):
        raise ValueError("설정에 model이 필요합니다")
    max_revisions = data.get("max_revisions")
    if type(max_revisions) is not int or max_revisions != 1:
        raise ValueError("이번 단계에서는 max_revisions: 1이 필요합니다")
    raw_roles = data.get("roles")
    if not isinstance(raw_roles, list) or not raw_roles:
        raise ValueError("설정에 roles 목록이 필요합니다")
    roles = []
    seen = set()
    for raw in raw_roles:
        if not isinstance(raw, dict):
            raise ValueError("각 역할은 YAML 객체여야 합니다")
        name, instruction, inputs = raw.get("name"), raw.get("instruction"), raw.get("inputs")
        if not isinstance(name, str) or not name.strip() or name in seen:
            raise ValueError("역할 이름이 없거나 중복되었습니다")
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError(f"{name}: 지시문이 필요합니다")
        if not isinstance(inputs, list) or not inputs or not all(isinstance(x, str) for x in inputs):
            raise ValueError(f"{name}: inputs 목록이 필요합니다")
        allowed = {"question", *(f"{prior}.output" for prior in seen)}
        if any(source not in allowed for source in inputs):
            raise ValueError(f"{name}: inputs는 질문 또는 앞 역할의 결과를 참조해야 합니다")
        kind = raw.get("kind", "step")
        if kind not in {"writer", "reviewer", "step"}:
            raise ValueError(f"{name}: 알 수 없는 kind입니다")
        roles.append(Role(name, instruction, tuple(inputs), kind))
        seen.add(name)
    kinds = [role.kind for role in roles]
    if kinds.count("writer") != 1 or kinds.count("reviewer") != 1:
        raise ValueError("writer와 reviewer 종류의 역할이 각각 하나씩 필요합니다")
    if kinds.index("writer") >= kinds.index("reviewer"):
        raise ValueError("writer가 reviewer보다 앞에 있어야 합니다")
    return Config(data["model"], tuple(roles), max_revisions)


def review_decision(output: str) -> str | None:
    lines = output.splitlines()
    if not lines:
        return None
    decision = lines[0].strip()
    if decision not in {"PASS", "FIX"}:
        return None
    if decision == "FIX" and not "\n".join(lines[1:]).strip():
        return None
    return decision


PLACEHOLDER_LABELS = frozenset({
    "날짜", "시간", "날짜 및 시간", "일시", "교체 예정일", "시행일", "시작일", "종료일",
    "담당자", "담당자 연락처", "연락처", "전화번호", "이메일", "장소", "미정", "추후 입력",
})
BRACKETED_LABEL = re.compile(r"\[([^\[\]\n]{1,30})\]")


def unfinished_placeholders(draft: str) -> list[str]:
    """Detect only explicit, common unfinished bracket labels, not arbitrary titles."""
    return [match.group(0) for match in BRACKETED_LABEL.finditer(draft)
            if " ".join(match.group(1).split()) in PLACEHOLDER_LABELS]


Event = Callable[[Role, int, str, RoleResult | None], None]


def execute(question: str, config: Config, llm: LLM, on_event: Event | None = None) -> RunResult:
    if not question.strip():
        raise ValueError("질문이 비어 있습니다")
    values = {"question": question}
    results: list[RoleResult] = []
    revisions = 0
    writer = next(role for role in config.roles if role.kind == "writer")

    def call(role: Role, *, retry: bool = False) -> str | None:
        sources = list(role.inputs)
        if retry:
            sources.extend(["previous_draft", "feedback"])
        prompt = "\n\n".join(f"[{source}]\n{values[source]}" for source in sources)
        attempt = revisions + 1
        if on_event:
            on_event(role, attempt, "running", None)
        started = perf_counter()
        try:
            output = llm.complete(model=config.model, role=role.name, instruction=role.instruction, prompt=prompt)
        except Exception:
            item = RoleResult(role.name, prompt, "", perf_counter() - started, attempt)
            results.append(item)
            if on_event:
                on_event(role, attempt, "failed", item)
            return None
        decision = review_decision(output) if role.kind == "reviewer" else None
        item = RoleResult(role.name, prompt, output, perf_counter() - started, attempt, decision, decision)
        results.append(item)
        values[f"{role.name}.output"] = output
        if on_event:
            on_event(role, attempt, "failed" if role.kind == "reviewer" and decision is None else "completed", item)
        return output

    for role in config.roles:
        if role.kind != "reviewer":
            if call(role) is None:
                return RunResult(tuple(results), revisions, "failed", f"{role.name} 호출 실패")
            continue
        while True:
            response = call(role)
            if response is None:
                return RunResult(tuple(results), revisions, "failed", "검토자 호출 실패")
            decision = results[-1].decision
            if decision is None:
                return RunResult(tuple(results), revisions, "failed", "검토자 응답 형식 오류")
            feedback = response.split("\n", 1)[1].strip() if decision == "FIX" else ""
            if decision == "PASS":
                placeholders = unfinished_placeholders(values[f"{writer.name}.output"])
                if placeholders:
                    feedback = (
                        "미완성 플레이스홀더가 남아 있습니다: " + ", ".join(placeholders)
                        + ". 원래 질문에 없는 사실을 만들어 채우지 말고 필요한 정보를 확인하세요."
                    )
                    decision = "FIX"
                    results[-1] = replace(results[-1], decision="FIX", validation_feedback=feedback)
                    if on_event:
                        on_event(role, revisions + 1, "completed", results[-1])
            if decision == "PASS":
                break
            if revisions >= config.max_revisions:
                if on_event:
                    on_event(role, revisions + 1, "failed", results[-1])
                return RunResult(tuple(results), revisions, "failed", "재작성 횟수 초과: 검토 미통과")
            values["previous_draft"] = values[f"{writer.name}.output"]
            values["feedback"] = feedback
            revisions += 1
            if call(writer, retry=True) is None:
                return RunResult(tuple(results), revisions, "failed", "재작성 호출 실패")
    return RunResult(tuple(results), revisions, "passed")


def run(question: str, config: Config, llm: LLM) -> list[RoleResult]:
    """Compatibility helper for successful sequential runs."""
    result = execute(question, config, llm)
    if result.status != "passed":
        raise RuntimeError(result.reason or "실행 실패")
    return list(result.results)
