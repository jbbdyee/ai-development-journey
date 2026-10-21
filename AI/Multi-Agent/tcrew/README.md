# tcrew

공지 역할 지시문을 바꿀 때마다 n8n 워크플로우를 열어 수정하는 대신, 터미널에서 역할별 결과를 확인하는 Python CLI입니다. 기본 실행 순서는 **Writer → Reviewer → Editor**이며, 역할 지시문과 입력 출처는 YAML에 둡니다.

## 동작

1. Writer가 질문의 사실을 바탕으로 초안을 작성합니다.
2. Reviewer가 첫 줄 `PASS` 또는 `FIX`와 의견을 반환합니다. `FIX`이면 Writer에게 원래 질문·이전 초안·검토 의견을 전달해 **최대 한 번** 재작성하고 재검토합니다.
3. Reviewer가 `PASS`라고 해도 초안에 `[날짜 및 시간]`, `[교체 예정일]`, `[담당자 연락처]`처럼 코드에 지정된 미완성 표제가 남아 있으면 유효 판정을 `FIX`로 바꿉니다. 재검토 후에도 통과하지 못하면 Editor를 실행하지 않고 실패로 종료합니다.
4. 통과한 초안은 Editor에게 전달됩니다. 역할별 입력·출력·시간과 최종 상태는 JSON으로 기록됩니다.

`PASS/FIX` 형식이 잘못된 응답도 통과 처리하지 않습니다. 검토 지시문은 질문에 없는 날짜·시간·연락처를 만들어내지 않도록 요청하지만, 코드가 모든 사실 오류를 판별하지는 않습니다.

## 설치와 실행

Python **3.11 이상**과 [uv](https://docs.astral.sh/uv/getting-started/installation/)가 필요합니다. Python은 [공식 다운로드](https://www.python.org/downloads/)에서 설치할 수 있습니다. 저장소 루트에서:

```bash
cd AI/Multi-Agent/tcrew
uv sync
```

실제 LLM 실행에는 환경 변수 `OPENAI_API_KEY`가 필요합니다. 키를 코드나 YAML에 저장하지 마세요. 설정 모델은 `gpt-4.1-mini`이며 다음 명령은 유료 API 호출을 할 수 있습니다.

```bash
uv run tcrew "10월 27일 VPN 인증서 교체 공지를 작성해 주세요" --plain
uv run tcrew "10월 27일 VPN 인증서 교체 공지를 작성해 주세요"
```

`--plain`은 역할별 응답을 터미널에 출력합니다. 옵션을 빼면 Textual TUI가 열립니다. TUI의 역할별 탭에는 상태·응답·소요 시간이 표시되고, 재작성·재검토는 `#1`과 `#2`로 구분됩니다. 화면 위쪽에서 전체 성공·실패와 재작성 횟수를 볼 수 있습니다. 아래 입력칸에서 새 질문을 입력하고 Enter로 실행하며 `q`로 종료합니다. LLM 호출은 백그라운드에서 실행됩니다.

## YAML로 역할 추가

[`crew.yaml`](crew.yaml)의 `roles` 순서대로 실행합니다. 각 역할의 `name`, `instruction`, `inputs`를 YAML에서 읽습니다. `inputs`는 `question` 또는 앞 역할의 `역할명.output`을 참조합니다. Writer와 Reviewer에는 각각 `kind: writer`, `kind: reviewer`를 지정합니다.

[`crew.translator.yaml`](crew.translator.yaml)은 Editor 뒤에 Translator를 추가하고 `editor.output`을 입력으로 받는 예시입니다. Python 코드를 바꾸지 않아도 네 번째 호출과 탭이 생성됩니다.

```bash
uv run tcrew "10월 27일 서비스 점검 공지를 작성해 주세요" --config crew.translator.yaml
```

Translator 지시문은 입력 표제 `[editor.output]` 없이 번역문만 반환하도록 요청합니다. 실제 모델이 언제나 이 지시를 따르는지까지 보장하지는 않습니다.

## 실행 기록과 보안

각 실행은 `runs/*.json`에 역할별 입력·출력·소요 시간·검토 판정, 재작성 횟수와 최종 상태를 저장합니다. `runs/`와 가상환경·캐시는 Git에서 제외합니다. 기록을 쓸 때 환경 변수의 API 키, Authorization Bearer 값, 이메일·한국 전화번호·주민등록번호 **형태**를 마스킹합니다. 역할 간 전달과 실제 LLM 입력은 원본 그대로입니다.

마스킹은 정해진 패턴에 한정됩니다. 이름·주소 등 모든 개인정보를 가리지는 못하며, TUI와 `--plain` 출력에서는 API 키·Authorization 외의 개인정보가 보일 수 있습니다. 기록이나 화면을 공유하기 전에 확인하세요.

## 검증과 제한사항

```bash
uv run pytest -q
```

2026-10-21 기준 가짜 LLM 회귀 테스트 **20개 통과**: 역할 순서와 전달, `FIX → PASS`, `FIX → FIX`, 잘못된 검토 응답, Reviewer 원문 `PASS`의 플레이스홀더 차단, 비동기 TUI, YAML Translator 확장, 기록 마스킹을 검사합니다. 테스트는 실제 OpenAI API를 호출하지 않습니다.

플레이스홀더 검사는 코드에 지정된 짧은 대괄호 표제만 찾으며 일반 문서 제목은 통과시킵니다. 미정인 날짜를 사전 안내로 표현할지처럼 문맥에 따른 게시 적합성, 근거 없는 사실 전체의 검증은 Reviewer 모델의 판단에 의존합니다. n8n 연결, 배치 실행, 여러 LLM 제공업체 지원은 구현하지 않았습니다.
