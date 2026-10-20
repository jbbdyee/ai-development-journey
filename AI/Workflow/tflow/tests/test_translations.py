import asyncio
from io import BytesIO
import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError

from textual.widgets import Static, Tree

from tflow.explanations import DescriptionCache, DescriptionService
from tflow.translations import TranslationService, openai_translator
from tflow.tui import TflowApp
from tflow.workflow import load_workflow


SOURCE = Path(__file__).parent / "fixtures/it-agent.json"
ASSISTANT = Path(__file__).parent / "fixtures/assistant.json"


class FakeTranslator:
    def __init__(self, fail=False, omit_segment=False):
        self.calls = []
        self.fail = fail
        self.omit_segment = omit_segment

    async def __call__(self, masked, api_key):
        self.calls.append(masked)
        if self.fail:
            raise RuntimeError("fake failure")
        segments = json.loads(masked)["segments"]
        if self.omit_segment:
            segments = segments[:-1]
        return json.dumps({"translations": {item["id"]: "이 워크플로우의 지시문을 한국어로 안내합니다."
                                             for item in segments}}, ensure_ascii=False)


def make_service(tmp_path, fake, key="test-only"):
    return TranslationService(DescriptionCache(tmp_path / "translations.json"), fake, key)


def test_translation_cache_and_source_change(tmp_path):
    async def run():
        fake = FakeTranslator()
        service = make_service(tmp_path, fake)
        source = "Use Search_FAQ and Get_ticket with gpt-4.1-mini at https://example.com/path."
        terms = ("Search_FAQ", "Get_ticket")
        first = await service.translate(source, terms)
        assert first.status == "새로 번역"
        assert all(term in first.text for term in ("Search_FAQ", "Get_ticket", "gpt-4.1-mini", "https://example.com/path"))
        assert len(fake.calls) == 1
        assert all(term not in fake.calls[0] for term in ("Search_FAQ", "Get_ticket", "gpt-4.1-mini", "https://example.com/path"))
        second = await service.translate(source, terms)
        assert second.status == "캐시 사용" and second.text == first.text
        assert len(fake.calls) == 1
        persisted = make_service(tmp_path, FakeTranslator())
        assert (await persisted.translate(source, terms)).status == "캐시 사용"
        assert persisted.translator.calls == []
        changed = await service.translate(source + " Then reply.", terms)
        assert changed.status == "새로 번역" and len(fake.calls) == 2
        cache_text = (tmp_path / "translations.json").read_text()
        assert source not in cache_text
        assert all(term not in cache_text for term in terms)
        assert "https://example.com/path" not in cache_text
    asyncio.run(run())


def test_translation_missing_key_failure_and_sensitive_input(tmp_path):
    async def run():
        source = "Explain a safe instruction."
        fake = FakeTranslator()
        missing = make_service(tmp_path, fake, key="")
        assert (await missing.translate(source)).status == "API 키 미설정 · 영어 원문"
        assert fake.calls == []
        failed = make_service(tmp_path, FakeTranslator(fail=True))
        assert (await failed.translate(source)).status == "요청 오류 · 영어 원문"
        malformed = make_service(tmp_path, FakeTranslator(omit_segment=True))
        partial = await malformed.translate("Use Search_FAQ and continue.")
        assert partial.status == "새로 번역" and "Search_FAQ" in partial.text
        class EmptyTranslator:
            async def __call__(self, payload, key):
                return '{"translations": {}}'
        empty = make_service(tmp_path / "empty", EmptyTranslator())
        assert (await empty.translate("Use Search_FAQ.")).status == "응답 검증 실패 · 영어 원문"
        sensitive = make_service(tmp_path, fake)
        secret = "Authorization: Bearer PRIVATE_TOKEN"
        assert (await sensitive.translate(secret)).status == "민감정보 감지 · 영어 원문"
        assert (await sensitive.translate("Safe message", ("Authorization: Bearer PRIVATE_TOKEN",))).status == "민감정보 감지 · 영어 원문"
        assert fake.calls == []
        assert "PRIVATE_TOKEN" not in (tmp_path / "translations.json").read_text()
    asyncio.run(run())


def test_safe_error_categories_and_normal_instruction(tmp_path):
    async def run():
        source = "A password is required for account access. Use Search_FAQ."
        normal = await make_service(tmp_path / "normal", FakeTranslator()).translate(source)
        assert normal.status == "새로 번역"

        class ErrorTranslator:
            def __init__(self, error):
                self.error = error

            async def __call__(self, masked, key):
                raise self.error

        cases = [
            (HTTPError("https://example.invalid", 401, "private response", {}, None), "인증 오류 · 영어 원문"),
            (HTTPError("https://example.invalid", 400, "private response", {}, None), "요청 오류 · 영어 원문"),
            (HTTPError("https://example.invalid", 429, "private response", {}, None), "요청 제한 · 영어 원문"),
            (URLError("private network detail"), "네트워크 오류 · 영어 원문"),
            (KeyError("private response field"), "응답 형식 오류 · 영어 원문"),
        ]
        for index, (error, expected) in enumerate(cases):
            service = make_service(tmp_path / str(index), ErrorTranslator(error))
            result = await service.translate("Use Search_FAQ.")
            assert result.status == expected
            assert "private" not in result.status
            assert service.cache.data == {}
    asyncio.run(run())


def test_openai_request_format_and_response_parsing(monkeypatch, tmp_path):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        answer = json.dumps({"translations": {"0": "한국어", "1": "설명"}}, ensure_ascii=False)
        return BytesIO(json.dumps({"choices": [{"message": {"content": answer}}]}).encode())

    monkeypatch.setattr("tflow.explanations.urlopen", fake_urlopen)
    service = make_service(tmp_path, openai_translator)
    result = asyncio.run(service.translate("Use Search_FAQ."))
    assert result.status == "새로 번역" and "Search_FAQ" in result.text
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer test-only"
    assert captured["body"]["model"] == "gpt-4.1-mini"
    sent_segments = json.loads(captured["body"]["messages"][1]["content"])["segments"]
    assert sent_segments == [{"id": "0", "text": "Use"}]
    assert "Search_FAQ" not in json.dumps(captured["body"])
    assert captured["timeout"] == 20

    def malformed_response(request, timeout):
        return BytesIO(b'{"choices": []}')

    monkeypatch.setattr("tflow.explanations.urlopen", malformed_response)
    broken = make_service(tmp_path / "broken", openai_translator)
    assert asyncio.run(broken.translate("Use Search_FAQ.")).status == "응답 형식 오류 · 영어 원문"


def test_fenced_json_and_old_cache_are_handled(tmp_path):
    async def fenced(payload, key):
        return '```json\n{"translations": {"0": "한국어 안내"}}\n```'

    source = "Use Search_FAQ."
    old_key = __import__("hashlib").sha256(
        json.dumps([1, "gpt-4.1-mini", source, []], ensure_ascii=False,
                   separators=(",", ":")).encode()
    ).hexdigest()
    old_cache = tmp_path / "translations.json"
    old_cache.write_text(json.dumps({old_key: "old ⟦T0⟧"}))
    result = asyncio.run(make_service(tmp_path, fenced).translate(source))
    assert result.status == "새로 번역"
    assert "한국어 안내 Search_FAQ." in result.text


def test_invalid_current_translation_cache_is_regenerated(tmp_path):
    source = "Use Search_FAQ."
    fake = FakeTranslator()
    service = make_service(tmp_path, fake)
    first = asyncio.run(service.translate(source))
    assert first.status == "새로 번역"
    key = next(iter(service.cache.data))
    service.cache.data[key] = '{"translations": {}}'
    second = asyncio.run(service.translate(source))
    assert second.status == "새로 번역"
    assert len(fake.calls) == 2


def test_tui_korean_english_toggle_and_expand(tmp_path):
    asyncio.run(_exercise_tui(tmp_path))


async def _exercise_tui(tmp_path):
    workflow = load_workflow(SOURCE)
    before = json.dumps(workflow.by_name["IT help agent"], sort_keys=True)
    fake = FakeTranslator()
    translations = make_service(tmp_path, fake)

    async def fake_explainer(context, key):
        return "IT 문의를 처리합니다."

    descriptions = DescriptionService(DescriptionCache(tmp_path / "descriptions.json"), fake_explainer, "test-only")
    app = TflowApp(workflow, SOURCE, descriptions, translations)
    async with app.run_test(size=(120, 32)) as pilot:
        tree = app.query_one("#flow-tree", Tree)
        def descendants(node):
            yield node
            for child in node.children:
                yield from descendants(child)
        agent = next(node for node in descendants(tree.root) if node.data == "IT help agent")
        tree.select_node(agent)
        await pilot.pause()
        detail = app.query_one("#detail-pane", Static).render().plain
        assert "지시문: 한국어 번역" in detail
        assert "상태: 새로 생성" in detail
        assert "번역 상태: 새로 번역" in detail
        assert "OpenAI chat model" in detail and "Search FAQ, Get ticket" in detail
        await pilot.press("e")
        english = app.query_one("#detail-pane", Static).render().plain
        assert "지시문: 영어 원문" in english and "v로 영어 원문 펼치기" in english
        await pilot.press("v")
        expanded = app.query_one("#detail-pane", Static).render().plain
        assert "v로 접기" in expanded
        assert len(expanded) > len(english)
        await pilot.press("e")
        assert "지시문: 한국어 번역" in app.query_one("#detail-pane", Static).render().plain
        tree.select_node(next(node for node in descendants(tree.root) if node.data == "IT question webhook"))
        tree.select_node(agent)
        await pilot.pause()
        assert "번역 상태: 캐시 사용" in app.query_one("#detail-pane", Static).render().plain
        assert len(fake.calls) == 1
    assert json.dumps(workflow.by_name["IT help agent"], sort_keys=True) == before


def test_tui_falls_back_to_english_without_key(tmp_path):
    asyncio.run(_exercise_no_key(tmp_path))


async def _exercise_no_key(tmp_path):
    workflow = load_workflow(SOURCE)
    fake = FakeTranslator()
    translations = make_service(tmp_path, fake, key="")
    descriptions = DescriptionService(DescriptionCache(tmp_path / "descriptions.json"),
                                      api_key="")
    app = TflowApp(workflow, SOURCE, descriptions, translations)
    async with app.run_test() as pilot:
        tree = app.query_one("#flow-tree", Tree)
        def find(node):
            if node.data == "IT help agent":
                return node
            for child in node.children:
                found = find(child)
                if found:
                    return found
            return None
        tree.select_node(find(tree.root))
        await pilot.pause()
        detail = app.query_one("#detail-pane", Static).render().plain
        assert "지시문: 영어 원문" in detail
        assert "번역 상태: API 키 미설정 · 영어 원문" in detail
        assert "하는 일: API 키 미설정" in detail
        await pilot.press("e")
        assert "지시문: 영어 원문" in app.query_one("#detail-pane", Static).render().plain
        assert fake.calls == []


def test_split_tasks_tui_translation_and_cache(tmp_path):
    asyncio.run(_exercise_split_tasks(tmp_path))


async def _exercise_split_tasks(tmp_path):
    workflow = load_workflow(ASSISTANT)
    fake = FakeTranslator()
    translations = make_service(tmp_path, fake)
    descriptions = DescriptionService(DescriptionCache(tmp_path / "descriptions.json"), api_key="")
    app = TflowApp(workflow, ASSISTANT, descriptions, translations)
    async with app.run_test() as pilot:
        tree = app.query_one("#flow-tree", Tree)
        def descendants(node):
            yield node
            for child in node.children:
                yield from descendants(child)
        agent = next(node for node in descendants(tree.root) if node.data == "Split tasks")
        webhook = next(node for node in descendants(tree.root) if node.data == "Assistant webhook")
        tree.select_node(agent)
        await pilot.pause()
        panel = app.query_one("#detail-pane", Static)
        assert "지시문: 한국어 번역" in panel.render().plain
        assert "번역 상태: 새로 번역" in panel.render().plain
        await pilot.press("e")
        assert "지시문: 영어 원문" in panel.render().plain
        await pilot.press("e")
        assert "지시문: 한국어 번역" in panel.render().plain
        tree.select_node(webhook)
        tree.select_node(agent)
        await pilot.pause()
        assert "번역 상태: 캐시 사용" in panel.render().plain
        assert len(fake.calls) == 1
