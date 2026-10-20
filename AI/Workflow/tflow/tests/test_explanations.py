import asyncio
import copy
import json
from pathlib import Path

from textual.widgets import Static, Tree

from tflow.explanations import DescriptionCache, DescriptionService, cache_key, safe_context
from tflow.tui import TflowApp
from tflow.workflow import Connection, load_workflow


SOURCE = Path(__file__).parent / "fixtures/it-agent.json"


class FakeExplainer:
    def __init__(self, answer="사내 IT 문의를 FAQ와 접수 조회 도구로 처리합니다.", fail=False):
        self.calls = []
        self.answer = answer
        self.fail = fail

    async def __call__(self, context, api_key):
        self.calls.append(copy.deepcopy(context))
        if self.fail:
            raise RuntimeError("test failure")
        return self.answer


def service(tmp_path, fake, key="test-only"):
    return DescriptionService(DescriptionCache(tmp_path / "descriptions.json"), fake, key)


def test_first_selection_then_cache_reuse(tmp_path):
    async def run():
        workflow = load_workflow(SOURCE)
        fake = FakeExplainer()
        descriptions = service(tmp_path, fake)
        first = await descriptions.describe(workflow, "IT help agent")
        second = await descriptions.describe(workflow, "IT help agent")
        assert first.status == "새로 생성" and first.text == fake.answer
        assert second.status == "캐시 사용" and second.text == fake.answer
        assert len(fake.calls) == 1
        fresh_service = service(tmp_path, FakeExplainer())
        assert (await fresh_service.describe(workflow, "IT help agent")).status == "캐시 사용"
        assert fresh_service.explainer.calls == []
    asyncio.run(run())


def test_cache_invalidates_on_setting_change(tmp_path):
    async def run():
        workflow = load_workflow(SOURCE)
        fake = FakeExplainer()
        descriptions = service(tmp_path, fake)
        await descriptions.describe(workflow, "IT help agent")
        workflow.by_name["IT help agent"]["parameters"]["options"]["systemMessage"] = "Answer only VPN questions."
        assert (await descriptions.describe(workflow, "IT help agent")).status == "새로 생성"
        assert len(fake.calls) == 2
    asyncio.run(run())


def test_cache_invalidates_on_connection_change(tmp_path):
    async def run():
        workflow = load_workflow(SOURCE)
        fake = FakeExplainer()
        descriptions = service(tmp_path, fake)
        await descriptions.describe(workflow, "IT help agent")
        workflow.connections.append(Connection("Reject empty", "IT help agent", "main", 0, 0))
        assert (await descriptions.describe(workflow, "IT help agent")).status == "새로 생성"
        assert len(fake.calls) == 2
    asyncio.run(run())


def test_missing_key_and_failed_request_are_not_cached(tmp_path):
    async def run():
        workflow = load_workflow(SOURCE)
        fake = FakeExplainer()
        missing = service(tmp_path, fake, key="")
        assert (await missing.describe(workflow, "IT help agent")).status == "API 키 미설정"
        assert fake.calls == []
        failing = service(tmp_path, FakeExplainer(fail=True))
        assert (await failing.describe(workflow, "IT help agent")).status == "설명 생성 실패"
        assert failing.cache.data == {}
        assert not (tmp_path / "descriptions.json").exists()
    asyncio.run(run())


def test_credentials_never_enter_request_or_cache(tmp_path):
    async def run():
        workflow = load_workflow(SOURCE)
        node = workflow.by_name["IT help agent"]
        node["credentials"] = {"openAiApi": {"id": "PRIVATE_CREDENTIAL_ID"}}
        node["parameters"]["options"]["systemMessage"] = "Authorization: Bearer PRIVATE_TOKEN"
        node["parameters"]["headerParameters"] = {"Authorization": "Bearer PRIVATE_TOKEN"}
        fake = FakeExplainer()
        descriptions = service(tmp_path, fake)
        result = await descriptions.describe(workflow, "IT help agent")
        assert result.status == "새로 생성"
        request = json.dumps(fake.calls, ensure_ascii=False)
        cache = (tmp_path / "descriptions.json").read_text()
        for secret in ("PRIVATE_CREDENTIAL_ID", "PRIVATE_TOKEN", "Authorization", "Bearer"):
            assert secret not in request
            assert secret not in cache
        assert cache_key(safe_context(workflow, "IT help agent")) in cache
    asyncio.run(run())


def test_tui_description_and_missing_key(tmp_path):
    async def run():
        workflow = load_workflow(SOURCE)
        fake = FakeExplainer()
        app = TflowApp(workflow, SOURCE, service(tmp_path, fake))
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
            assert "지시문:" in detail and "Search FAQ, Get ticket" in detail
            assert "하는 일: 사내 IT 문의" in detail
            assert "상태: 새로 생성" in detail
        no_key = TflowApp(workflow, SOURCE, service(tmp_path / "other", FakeExplainer(), key=""))
        async with no_key.run_test() as pilot:
            tree = no_key.query_one("#flow-tree", Tree)
            tree.select_node(find(tree.root))
            await pilot.pause()
            detail = no_key.query_one("#detail-pane", Static).render().plain
            assert "Search FAQ, Get ticket" in detail
            assert "하는 일: API 키 미설정" in detail
    asyncio.run(run())
