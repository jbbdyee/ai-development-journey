import json
from pathlib import Path

from tcrew.cli import main
from tcrew.core import execute, load_config


CONFIG = Path(__file__).resolve().parents[1] / "crew.yaml"


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def complete(self, *, model, role, instruction, prompt):
        self.calls.append((role, prompt))
        return next(self.responses)


def test_pass_path_calls_editor_and_records_each_role(tmp_path):
    fake = ScriptedLLM(["초안", "PASS\n좋습니다", "최종안"])
    assert main(["VPN 공지", "--plain", "--config", str(CONFIG)], llm=fake, runs_dir=tmp_path) == 0
    assert [name for name, _ in fake.calls] == ["writer", "reviewer", "editor"]
    record = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert record["status"] == "passed"
    assert record["revisions"] == 0
    assert [(item["name"], item["decision"]) for item in record["roles"]] == [
        ("writer", None), ("reviewer", "PASS"), ("editor", None)
    ]
    assert all(item["duration_seconds"] >= 0 for item in record["roles"])
    assert "초안" in record["roles"][1]["input"]


def test_fix_then_pass_passes_original_question_draft_and_feedback():
    fake = ScriptedLLM(["첫 초안", "FIX\n연락처를 빼세요", "수정 초안", "PASS\n승인", "최종안"])
    result = execute("원래 질문", load_config(CONFIG), fake)
    assert result.status == "passed"
    assert result.revisions == 1
    assert [name for name, _ in fake.calls] == ["writer", "reviewer", "writer", "reviewer", "editor"]
    revised_input = fake.calls[2][1]
    assert "원래 질문" in revised_input
    assert "첫 초안" in revised_input
    assert "연락처를 빼세요" in revised_input
    assert "수정 초안" in fake.calls[3][1]
    assert [item.attempt for item in result.results] == [1, 1, 2, 2, 2]


def test_always_fix_stops_after_four_calls_and_records_failure(tmp_path):
    fake = ScriptedLLM(["첫 초안", "FIX\n고치세요", "수정 초안", "FIX\n아직 문제"])
    assert main(["질문", "--plain", "--config", str(CONFIG)], llm=fake, runs_dir=tmp_path) == 1
    assert [name for name, _ in fake.calls] == ["writer", "reviewer", "writer", "reviewer"]
    record = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert record["status"] == "failed"
    assert record["revisions"] == 1
    assert record["roles"][-1]["decision"] == "FIX"


def test_invalid_review_never_approves_or_calls_editor(tmp_path):
    for index, invalid in enumerate(["", "MAYBE\n좋습니다", "FIX", "pass\n좋습니다"]):
        fake = ScriptedLLM(["초안", invalid])
        result = execute("질문", load_config(CONFIG), fake)
        assert result.status == "failed"
        assert [name for name, _ in fake.calls] == ["writer", "reviewer"]
        assert result.results[-1].decision is None
        record_path = tmp_path / str(index)
        record_path.mkdir()
        from tcrew.records import save_record
        record = json.loads(save_record(result, record_path).read_text())
        assert record["status"] == "failed"


def test_invalid_second_review_stops_before_editor():
    fake = ScriptedLLM(["초안", "FIX\n고치세요", "수정안", "알 수 없는 답"])
    result = execute("질문", load_config(CONFIG), fake)
    assert result.status == "failed"
    assert result.revisions == 1
    assert [name for name, _ in fake.calls] == ["writer", "reviewer", "writer", "reviewer"]


def test_api_key_and_authorization_are_redacted_from_record(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-example-secret")
    fake = ScriptedLLM(["sk-example-secret", "PASS\nAuthorization: Bearer token-123", "완료"])
    assert main(["질문", "--plain", "--config", str(CONFIG)], llm=fake, runs_dir=tmp_path) == 0
    content = next(tmp_path.glob("*.json")).read_text()
    displayed = capsys.readouterr().out
    assert "sk-example-secret" not in content
    assert "token-123" not in content
    assert "sk-example-secret" not in displayed
    assert "token-123" not in displayed
    assert "[REDACTED]" in content


def test_personal_information_is_masked_only_when_record_is_saved(tmp_path):
    from tcrew.records import save_record

    email = "notice@example.com"
    mobile = "010-0000-0000"
    landline = "02-000-0000"
    resident_id = "991332-1234567"  # 존재할 수 없는 날짜의 합성 테스트 값
    question = f"공지 연락처 {email}, {mobile}"
    fake = ScriptedLLM([
        f"첫 초안: {email}",
        f"FIX\n연락처 {landline}과 {resident_id}을 삭제하세요",
        "수정 초안",
        "PASS\n승인",
        "최종안",
    ])
    result = execute(question, load_config(CONFIG), fake)
    assert result.status == "passed"
    assert result.revisions == 1
    assert [name for name, _ in fake.calls] == ["writer", "reviewer", "writer", "reviewer", "editor"]
    assert email in fake.calls[0][1]  # 실제 LLM 입력은 원본이다.
    assert email in fake.calls[1][1]
    assert landline in fake.calls[2][1]  # 검토 의견도 원본 그대로 재작성에 전달된다.
    assert resident_id in fake.calls[2][1]
    assert result.results[1].decision == "FIX"
    assert result.results[3].decision == "PASS"

    record = json.loads(save_record(result, tmp_path).read_text())
    content = json.dumps(record, ensure_ascii=False)
    for private_value in (email, mobile, landline, resident_id):
        assert private_value not in content
    for marker in ("[EMAIL_REDACTED]", "[PHONE_REDACTED]", "[ID_REDACTED]"):
        assert marker in content
    assert record["status"] == "passed"
    assert record["revisions"] == 1
    assert [item["decision"] for item in record["roles"] if item["name"] == "reviewer"] == ["FIX", "PASS"]


def test_record_redaction_handles_common_phone_formats_and_keeps_dates():
    from tcrew.records import redact_record

    value = "01000000000 / +82 10-0000-0000 / 031.000.0000 / 2026-10-27"
    redacted = redact_record(value)
    assert "01000000000" not in redacted
    assert "+82 10-0000-0000" not in redacted
    assert "031.000.0000" not in redacted
    assert redacted.count("[PHONE_REDACTED]") == 3
    assert "2026-10-27" in redacted


def test_reviewer_pass_with_placeholder_is_treated_as_fix():
    fake = ScriptedLLM([
        "[교체 예정일]에 인증서를 교체합니다.",
        "PASS\n좋습니다",
        "10월 27일에 인증서를 교체합니다.",
        "PASS\n승인",
        "최종 공지",
    ])
    result = execute("10월 27일 인증서 교체 공지", load_config(CONFIG), fake)
    assert result.status == "passed"
    assert result.revisions == 1
    assert [name for name, _ in fake.calls] == ["writer", "reviewer", "writer", "reviewer", "editor"]
    assert result.results[1].reviewer_decision == "PASS"
    assert result.results[1].decision == "FIX"
    assert "[교체 예정일]" in result.results[1].validation_feedback
    assert "[교체 예정일]" in fake.calls[2][1]
    assert "원래 질문에 없는 사실을 만들어" in fake.calls[2][1]
    assert result.results[3].decision == "PASS"


def test_persistent_placeholder_after_revision_fails_closed(tmp_path):
    fake = ScriptedLLM([
        "방문 시간: [날짜 및 시간]",
        "PASS\n좋습니다",
        "방문 시간: [날짜 및 시간]",
        "PASS\n좋습니다",
    ])
    assert main(["방문 공지를 써 주세요", "--plain", "--config", str(CONFIG)], llm=fake, runs_dir=tmp_path) == 1
    assert [name for name, _ in fake.calls] == ["writer", "reviewer", "writer", "reviewer"]
    record = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert record["status"] == "failed"
    assert record["revisions"] == 1
    assert [item["decision"] for item in record["roles"] if item["name"] == "reviewer"] == ["FIX", "FIX"]
    assert [item["reviewer_decision"] for item in record["roles"] if item["name"] == "reviewer"] == ["PASS", "PASS"]


def test_normal_bracketed_title_does_not_block_pass():
    fake = ScriptedLLM(["[VPN 인증서 교체 안내]\n10월 27일 교체합니다.", "PASS\n승인", "최종 공지"])
    result = execute("10월 27일 VPN 인증서 교체 공지", load_config(CONFIG), fake)
    assert result.status == "passed"
    assert result.revisions == 0
    assert [name for name, _ in fake.calls] == ["writer", "reviewer", "editor"]


def test_only_known_unfinished_bracket_labels_are_blocked():
    from tcrew.core import unfinished_placeholders

    draft = "[날짜 및 시간] [교체 예정일] [담당자 연락처] [VPN 인증서 교체 안내] [참고]"
    assert unfinished_placeholders(draft) == ["[날짜 및 시간]", "[교체 예정일]", "[담당자 연락처]"]


def test_writer_and_reviewer_instructions_cover_missing_facts():
    root = CONFIG.parent
    for config_path in (CONFIG, root / "crew.translator.yaml"):
        config = load_config(config_path)
        writer = next(role for role in config.roles if role.kind == "writer")
        reviewer = next(role for role in config.roles if role.kind == "reviewer")
        assert "임의로 확정하지 마세요" in writer.instruction
        assert "사실을 만들어" in writer.instruction
        assert "플레이스홀더" in reviewer.instruction
        assert "FIX" in reviewer.instruction
        assert "누락된 정보" in reviewer.instruction
