"""Separate, secret-aware Korean translation of Agent system messages."""

import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
import re
from typing import Awaitable, Callable, Sequence
from urllib.error import HTTPError, URLError

from .explanations import DescriptionCache, MODEL, openai_chat


TRANSLATION_VERSION = 2
SENSITIVE = re.compile(
    r"(?i)(?:authorization\s*:|bearer\s+\S+|sk-[A-Za-z0-9]{8,}|"
    r"(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|credential)"
    r"\s*(?::|=)\s*\S+|"
    r"(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret)"
    r"\s+(?:is|equals)\s+(?:['\"][^'\"]+['\"]|[A-Za-z0-9_/-]{12,}))"
)
OUTPUT_SECRET = re.compile(r"(?i)(?:bearer\s+\S+|sk-[A-Za-z0-9]{8,}|authorization\s*:\s*\S+)")
PROTECTED = re.compile(
    r"https?://[^\s]+|`[^`]+`|[\"'][A-Za-z][A-Za-z0-9_.-]*[\"']|"
    r"\$[A-Za-z][\w.]*(?:\([^)]*\))?|"
    r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b|"
    r"\b[A-Za-z]+-[A-Za-z0-9][A-Za-z0-9.-]*\b|\b[A-Z]{2,}\b|"
    r"\b[A-Z][a-z]+(?:[A-Z][a-zA-Z0-9]+)+\b"
)


def _protected_message(source: str, terms: Sequence[str]) -> tuple[str, list[str]]:
    """Replace code, URLs, identifiers, model and Tool names before transmission."""
    spans = [(m.start(), m.end()) for m in PROTECTED.finditer(source)]
    for term in sorted(set(terms), key=len, reverse=True):
        if term:
            spans.extend((m.start(), m.end()) for m in re.finditer(re.escape(term), source))
    spans.sort(key=lambda pair: (pair[0], -(pair[1] - pair[0])))
    chosen: list[tuple[int, int]] = []
    for start, end in spans:
        if not chosen or start >= chosen[-1][1]:
            chosen.append((start, end))
    values: list[str] = []
    chunks: list[str] = []
    pos = 0
    for start, end in chosen:
        chunks.append(source[pos:start])
        chunks.append(f"⟦T{len(values)}⟧")
        values.append(source[start:end])
        pos = end
    chunks.append(source[pos:])
    return "".join(chunks), values


async def openai_translator(masked_message: str, api_key: str) -> str:
    return await openai_chat(
        "입력 JSON의 segments 배열에서 각 text를 자연스러운 한국어로 번역하세요. 명령의 의미를 바꾸지 마세요. 응답은 JSON 객체 {\"translations\": {\"id\": \"한국어 번역\"}}만 반환하세요. 각 id를 유지하고 설명이나 코드 블록을 덧붙이지 마세요.",
        masked_message, api_key,
    )


@dataclass(frozen=True)
class TranslationResult:
    text: str | None
    status: str


class TranslationValidationError(ValueError):
    """The model did not return a usable translation."""


def _segments(masked: str) -> list[str]:
    return re.split(r"⟦T\d+⟧", masked)


def _translation_request(parts: list[str]) -> tuple[str, dict[str, tuple[str, str, str]]]:
    context: dict[str, tuple[str, str, str]] = {}
    segments = []
    for index, part in enumerate(parts):
        match = re.fullmatch(r"(\s*)(.*?)(\s*)", part, flags=re.DOTALL)
        assert match is not None
        before, core, after = match.groups()
        if re.search(r"[A-Za-z]", core):
            key = str(index)
            context[key] = (before, core, after)
            segments.append({"id": key, "text": core})
    return json.dumps({"segments": segments}, ensure_ascii=False), context


def _translated_parts(raw: str, parts: list[str], context: dict[str, tuple[str, str, str]]) -> list[str]:
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
        payload = json.loads(cleaned)
        if not isinstance(payload, dict):
            raise TypeError("translation response must be an object")
        translated = payload.get("translations", payload)
        if isinstance(translated, list):
            translated = {str(item["id"]): item["text"] for item in translated}
        if not isinstance(translated, dict):
            raise TypeError("translations must be an object")
    except (ValueError, KeyError, TypeError) as error:
        raise TranslationValidationError("invalid translation JSON") from error
    result = list(parts)
    translated_count = 0
    for key, (before, original, after) in context.items():
        value = translated.get(key)
        if isinstance(value, str) and value.strip() and not SENSITIVE.search(value) and not OUTPUT_SECRET.search(value):
            result[int(key)] = before + value.strip() + after
            translated_count += 1
        else:
            result[int(key)] = before + original + after
    if not translated_count:
        raise TranslationValidationError("no usable translated segments")
    return result


def _cache_payload(raw: str, context: dict[str, tuple[str, str, str]]) -> str:
    """Store only accepted translated text, never unrelated model output."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    payload = json.loads(cleaned)
    translated = payload.get("translations", payload)
    if isinstance(translated, list):
        translated = {str(item["id"]): item["text"] for item in translated}
    accepted = {key: value for key, value in translated.items()
                if key in context and isinstance(value, str) and value.strip()
                and not SENSITIVE.search(value) and not OUTPUT_SECRET.search(value)}
    return json.dumps({"translations": accepted}, ensure_ascii=False)


def _failure_status(error: Exception) -> str:
    if isinstance(error, TranslationValidationError):
        return "응답 검증 실패 · 영어 원문"
    if isinstance(error, HTTPError):
        if error.code in (401, 403):
            return "인증 오류 · 영어 원문"
        if error.code == 429:
            return "요청 제한 · 영어 원문"
        return "요청 오류 · 영어 원문"
    if isinstance(error, (URLError, TimeoutError, OSError)):
        return "네트워크 오류 · 영어 원문"
    if isinstance(error, (KeyError, IndexError, TypeError, AttributeError, json.JSONDecodeError)):
        return "응답 형식 오류 · 영어 원문"
    return "요청 오류 · 영어 원문"


class TranslationService:
    def __init__(self, cache: DescriptionCache,
                 translator: Callable[[str, str], Awaitable[str]] = openai_translator,
                 api_key: str | None = None) -> None:
        self.cache = cache
        self.translator = translator
        self.api_key = os.environ.get("OPENAI_API_KEY", "") if api_key is None else api_key
        self._lock = asyncio.Lock()

    async def translate(self, source: str, protected_terms: Sequence[str] = ()) -> TranslationResult:
        if not source.strip():
            return TranslationResult(None, "지시문 없음")
        # Refuse to transmit a message with an apparent literal secret.
        if SENSITIVE.search(source) or any(SENSITIVE.search(term) for term in protected_terms) or "```" in source:
            return TranslationResult(None, "민감정보 감지 · 영어 원문")
        key_material = json.dumps([TRANSLATION_VERSION, MODEL, source, sorted(set(protected_terms))],
                                  ensure_ascii=False, separators=(",", ":"))
        key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
        masked, values = _protected_message(source, protected_terms)
        parts = _segments(masked)
        request, context = _translation_request(parts)
        if not context:
            return TranslationResult(None, "번역할 자연어 없음 · 영어 원문")

        def restore(cached_json: str) -> str:
            translated_parts = _translated_parts(cached_json, parts, context)
            return "".join(part + (values[i] if i < len(values) else "")
                           for i, part in enumerate(translated_parts))

        cached = self.cache.get(key)
        if cached:
            try:
                return TranslationResult(restore(cached), "캐시 사용")
            except TranslationValidationError:
                pass
        if not self.api_key:
            return TranslationResult(None, "API 키 미설정 · 영어 원문")
        async with self._lock:
            cached = self.cache.get(key)
            if cached:
                try:
                    return TranslationResult(restore(cached), "캐시 사용")
                except TranslationValidationError:
                    pass
            try:
                translated_json = (await self.translator(request, self.api_key)).strip()
                if not translated_json or OUTPUT_SECRET.search(translated_json):
                    raise TranslationValidationError("unsafe or empty translation")
                translated = restore(translated_json)
                self.cache.put(key, _cache_payload(translated_json, context))
            except Exception as error:
                return TranslationResult(None, _failure_status(error))
            return TranslationResult(translated, "새로 번역")
