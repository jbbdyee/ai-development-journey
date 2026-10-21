import asyncio
import threading
from pathlib import Path

from textual.widgets import TabPane

from tcrew.core import execute, load_config
from tcrew.tui import CrewApp


ROOT = Path(__file__).resolve().parents[1]


class ScriptedLLM:
    def __init__(self, responses, gate=None):
        self.responses = iter(responses)
        self.calls = []
        self.gate = gate

    def complete(self, *, model, role, instruction, prompt):
        self.calls.append((role, prompt))
        if self.gate and len(self.calls) == 1:
            assert self.gate.wait(timeout=3)
        return next(self.responses)


async def wait_until(predicate):
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("TUI 실행이 끝나지 않았습니다")


def test_translator_from_yaml_runs_fourth_and_receives_editor_output():
    fake = ScriptedLLM(["초안", "PASS\n승인", "최종안", "English notice"])
    config = load_config(ROOT / "crew.translator.yaml")
    result = execute("질문", config, fake)
    assert result.status == "passed"
    assert [name for name, _ in fake.calls] == ["writer", "reviewer", "editor", "translator"]
    assert "최종안" in fake.calls[3][1]


def test_translator_instruction_requests_translation_only_despite_input_label():
    class InstructionFollowingFake:
        def __init__(self):
            self.translator_prompt = None
            self.translator_instruction = None

        def complete(self, *, model, role, instruction, prompt):
            if role == "reviewer":
                return "PASS\n승인"
            if role == "translator":
                self.translator_prompt = prompt
                self.translator_instruction = instruction
                assert prompt.startswith("[editor.output]\n")
                assert "번역문만 출력" in instruction
                assert "[editor.output]" in instruction
                assert "포함하지 마세요" in instruction
                return "Service maintenance notice"
            return "공지 초안" if role == "writer" else "최종 공지"

    fake = InstructionFollowingFake()
    result = execute("질문", load_config(ROOT / "crew.translator.yaml"), fake)
    assert result.status == "passed"
    assert fake.translator_prompt == "[editor.output]\n최종 공지"
    assert result.results[-1].output == "Service maintenance notice"
    assert "[editor.output]" not in result.results[-1].output


def test_tui_tabs_update_without_blocking_and_show_fix_pass(tmp_path):
    async def scenario():
        gate = threading.Event()
        fake = ScriptedLLM(["첫 초안", "FIX\n시작일 보완", "수정 초안", "PASS\n승인", "최종안"], gate)
        app = CrewApp("질문", load_config(ROOT / "crew.yaml"), fake, tmp_path)
        async with app.run_test() as pilot:
            try:
                assert len(app.query(TabPane)) == 3
                await wait_until(lambda: app.states["writer"] == "running")
                assert app.states["reviewer"] == "waiting"
                await pilot.press("tab")  # 첫 LLM 응답을 기다리는 동안에도 이벤트 루프가 동작한다.
            finally:
                gate.set()
            await wait_until(lambda: app.result is not None)
            assert app.result.status == "passed"
            assert app.result.revisions == 1
            assert app.states == {"writer": "completed", "reviewer": "completed", "editor": "completed"}
            assert len(app.history["writer"]) == 2
            assert "첫 초안" in app.history["writer"][0]
            assert "수정 초안" in app.history["writer"][1]
            assert len(app.history["reviewer"]) == 2
            assert "판정 FIX" in app.history["reviewer"][0]
            assert "시작일 보완" in app.history["reviewer"][0]
            assert "판정 PASS" in app.history["reviewer"][1]
            assert "완료" in app.query_one("#role-0", TabPane).title
            assert app.record_path and app.record_path.exists()
    asyncio.run(scenario())


def test_tui_fix_fix_stops_without_editor(tmp_path):
    async def scenario():
        fake = ScriptedLLM(["첫 초안", "FIX\n보완", "수정 초안", "FIX\n아직 부족"])
        app = CrewApp("질문", load_config(ROOT / "crew.yaml"), fake, tmp_path)
        async with app.run_test():
            await wait_until(lambda: app.result is not None)
            assert [name for name, _ in fake.calls] == ["writer", "reviewer", "writer", "reviewer"]
            assert app.result.status == "failed"
            assert app.result.revisions == 1
            assert app.states["reviewer"] == "failed"
            assert app.states["editor"] == "waiting"
            assert len(app.history["reviewer"]) == 2
    asyncio.run(scenario())


def test_translator_tui_tab_is_created_from_yaml(tmp_path):
    async def scenario():
        fake = ScriptedLLM(["초안", "PASS\n승인", "최종안", "English notice"])
        app = CrewApp("질문", load_config(ROOT / "crew.translator.yaml"), fake, tmp_path)
        async with app.run_test():
            assert len(app.query(TabPane)) == 4
            await wait_until(lambda: app.result is not None)
            assert app.states["translator"] == "completed"
            assert "English notice" in app.history["translator"][0]
            assert "translator" in app.query_one("#role-3", TabPane).title
    asyncio.run(scenario())
