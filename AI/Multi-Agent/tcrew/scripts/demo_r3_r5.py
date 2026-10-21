"""Offline R3/R5 demonstration with fixed, nonpersonal fake responses."""

import argparse
import json
from pathlib import Path

from tcrew.core import execute, load_config
from tcrew.records import save_record


ROOT = Path(__file__).resolve().parents[1]
FEEDBACK = "공지 시작일을 더 분명히 쓰세요"
FIRST_DRAFT = "서비스 점검 안내 초안"
REVISED_DRAFT = "10월 27일 서비스 점검 안내"


class FakeLLM:
    def __init__(self, responses: list[str]):
        self.responses = iter(responses)
        self.calls: list[str] = []

    def complete(self, *, model: str, role: str, instruction: str, prompt: str) -> str:
        self.calls.append(role)
        return next(self.responses)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=["fix-pass", "fix-fix"])
    args = parser.parse_args()

    responses = [FIRST_DRAFT, f"FIX\n{FEEDBACK}", REVISED_DRAFT]
    responses += ["PASS\n승인", "최종 공지"] if args.scenario == "fix-pass" else ["FIX\n시작일을 다시 확인하세요"]
    fake = FakeLLM(responses)
    result = execute("서비스 점검 공지를 작성해 주세요", load_config(ROOT / "crew.yaml"), fake)
    path = save_record(result, ROOT / "runs" / "demo")
    record = json.loads(path.read_text(encoding="utf-8"))

    assert fake.calls == (["writer", "reviewer", "writer", "reviewer", "editor"]
                          if args.scenario == "fix-pass" else ["writer", "reviewer", "writer", "reviewer"])
    assert FEEDBACK in result.results[2].input
    assert FIRST_DRAFT in result.results[2].input
    assert result.revisions == 1
    assert result.status == ("passed" if args.scenario == "fix-pass" else "failed")
    assert [item["decision"] for item in record["roles"] if item["name"] == "reviewer"] == (
        ["FIX", "PASS"] if args.scenario == "fix-pass" else ["FIX", "FIX"]
    )

    print(f"시나리오: {args.scenario} (가짜 LLM, API 호출 0회)")
    print("호출 순서: " + " → ".join(fake.calls))
    print(f"호출 횟수: {len(fake.calls)} / Editor 호출: {'예' if 'editor' in fake.calls else '아니요'}")
    print("재작성 입력: 이전 초안 포함=예, 첫 FIX 의견 포함=예")
    print("Reviewer 판정: " + " → ".join(item["decision"] for item in record["roles"] if item["name"] == "reviewer"))
    print(f"재작성 횟수: {record['revisions']} / 최종 상태: {record['status']}")
    print(f"기록: {path.relative_to(ROOT)}")
    print("JSON 필드: " + ", ".join(record.keys()))
    print("역할별 필드: " + ", ".join(record["roles"][0].keys()))


if __name__ == "__main__":
    main()
