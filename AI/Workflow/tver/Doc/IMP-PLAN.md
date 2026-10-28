# tver IMP-PLAN

## 진행 원칙

`Doc/SPEC.md`의 확인 방법을 기준으로 엔진을 먼저 만들고 TUI는 엔진의 변경 목록을 표시한다. 단계마다 해당 범위만 구현하고 `pytest`와 직접 실행으로 확인한 뒤 체크한다. 체크는 pytest와 직접 실행으로 확인한 항목만 표시한다. 기준 자료는 강의 자료(`<74>` = `Last3Mon/74`)의 `reference/helpdesk-v1.json`·`helpdesk-v2.json`이며, 테스트가 외부 경로에 의존하지 않도록 같은 파일을 `tests/data/`에 복사해 쓴다.

## 엔진 1단계 · 정리하고 비교하기 (R1~R4)

- [x] 워크플로우 JSON을 읽고 검증하는 함수와 `clean(workflow)`을 만든다. 노드 이름순·키 정렬, 의미 없는 메타데이터 제거, 연결 정규화를 적용한다.
- [x] `compare(old, new)`가 추가·삭제 노드, 설정의 점 경로별 변경, 연결의 추가·삭제를 `Change{op, node, category, key, before, after, lines}` 목록으로 돌려준다.
- [x] `category()`에 모델·지시문·흐름 분류 규칙을 넣고 한 줄 `summary()`를 만든다.
- [x] 긴 값과 여러 줄 값의 줄 단위 차이를 만든다.
- [x] `tver diff a.json b.json` CLI를 연결한다.
- [x] 기준 테스트: v1 → v2 변경 7개, model 1·prompt 1·flow 5, `[FAQ-003]` 추가 줄.
- [x] 무변경 테스트: 위치·id·노드 순서·키 순서만 바꾼 파일의 변경 0개. 고정 자료 `tests/data/helpdesk-v1-moved.json`(`tests/tools/make_moved.py`로 생성)과 무작위 섞기 5회로 확인한다.

확인: `uv run pytest -q`, `uv run tver diff <74>/reference/helpdesk-v1.json <74>/reference/helpdesk-v2.json`.

결과(2026-10-28): `uv run pytest -q` 33 passed. v1 → v2는 `7 change(s) · model 1 · prompt 1 · flow 5`이고 `systemMessage`에 `+ … [FAQ-003] …` 한 줄이 추가로 보인다. `helpdesk-v1-moved.json`과의 비교는 `0 change(s)`다. 엔진은 `src/tver/engine.py`, CLI는 `src/tver/cli.py`다.

## 엔진 2단계 · git 저장과 목록 (R5~R6)

- [x] `--repo`와 `TVER_REPO`를 받아 기본 `~/.tver/store`와 분리한다.
- [x] `save`가 정리된 JSON만 저장하고 직전 버전과 비교해 요약 커밋 메시지를 만든다. 변경이 없으면 `no change`로 끝낸다.
- [x] `log`가 커밋·시각·작성자·요약을 보여 준다. 이름 없이 `tver log`를 실행하면 저장된 워크플로우와 버전 수를 보여 준다.
- [x] 저장된 임의의 두 revision을 읽어 엔진 1단계의 `compare()`로 비교한다.
- [x] 테스트는 `tmp_path` 저장소만 사용하고 동일 파일 두 번 저장 시 버전 1개를 검증한다. 모든 테스트에서 `HOME`·`TVER_REPO`를 임시 폴더로 바꾸며, 버전 수는 tver가 아닌 `git rev-list --count`로 직접 센다.

확인: `uv run pytest -q`; `uv run tver --repo /tmp/tver-try save <v1>` 두 번; `uv run tver --repo /tmp/tver-try log helpdesk-v1.json`; 두 버전 저장 후 revision 비교.

결과(2026-10-28): `uv run pytest -q` 50 passed. 격리 저장소 `/tmp/tver-demo/store`에 `-n helpdesk`로 v1·v2를 저장하면 `first version · 9 node(s)`, `7 change(s) · model 1 · prompt 1 · flow 5`이고, v2를 다시 저장하면 `no change`다. `tver log helpdesk`는 2줄, `git rev-list --count HEAD`는 2다. 위치만 바꾼 사본 저장도 `no change`다. `tver diff <rev1> <rev2> helpdesk` 결과는 파일 비교와 본문·요약이 같다. 저장소 코드는 `src/tver/store.py`다.

## TUI 1단계 · 목록, 트리, 상세 (R8)

- [x] `tver <파일> [-n 이름]`에서 저장된 버전 목록을 최신순(`#번호 해시 시각` + 요약)으로 표시한다.
- [x] 버전 선택 시 worker에서 그 버전과 직전 버전을 읽어 비교하고 노드별 변경 트리를 갱신한다. 첫 버전은 빈 워크플로우와 비교해 모든 노드를 추가로 보여 준다. 연결 변경은 보내는 노드 아래에 둔다.
- [x] 변경 선택 시 전·후 값 또는 줄 단위 차이를 아래 패널에 표시한다. 노드 추가·삭제는 해당 노드의 정리된 설정을 보여 준다. 버전을 고르면 첫 변경이 자동으로 선택된다.
- [x] `[s]`로 현재 파일을 저장하고 목록·선택 상태를 갱신한다. 첫 버전과 변경 없는 경우도 다룬다. 아래 상태 줄에 현재 파일과 최신 버전의 차이 요약을 보여 준다.
- [x] 비교·저장 로직은 엔진 함수만 호출하도록 유지한다(`src/tver/tui.py`는 `engine.compare`·`Store.read/save/versions`만 사용).

확인: `uv run pytest -q`; `uv run tver <v1>`에서 목록·트리·상세 확인, 파일을 바꿔 `[s]` 후 새 버전 확인.

결과(2026-10-28): `uv run pytest -q` 55 passed. `tests/test_tui.py`는 Textual `run_test`로 실제 화면을 구동한다. 확인 내용은 목록 2줄, 트리 7개 변경(4개 노드), 첫 선택 `systemMessage`와 화면의 `FAQ-003`, 아래로 이동 시 모델 전후 값, 이전 버전 선택 시 노드 9개 추가, `[s]`로 새 변경 저장(3개) 뒤 다시 `[s]` 해도 3개 유지, 빈 저장소의 첫 저장이다. 격리 저장소 `/tmp/tver-demo/store`에서 `TVER_REPO=/tmp/tver-demo/store uv run tver tests/data/helpdesk-v2.json -n helpdesk`로 같은 화면을 확인했다.

## 설치와 다른 폴더에서 사용 (R14)

- [x] `pyproject.toml`의 `[project.scripts]`에 `tver`를 등록한다.
- [x] `uv tool install --editable .`로 설치하고 `uv tool list`, `which tver`를 확인한다.
- [x] 다른 폴더에서 `tver --help`와 기준 v1·v2 diff를 실행한다.

확인: `cd /tmp && tver --help`; `<74>` 폴더에서 `tver diff reference/helpdesk-v1.json reference/helpdesk-v2.json`.

결과(2026-10-28): `uv tool install --editable .` 후 `uv tool list`에 `tver v0.1.0`, `which tver`는 `~/.local/bin/tver`다. `/tmp`에서 `tver --help`, `<74>` 폴더에서 v1·v2 diff(`7 change(s) · model 1 · prompt 1 · flow 5`), `/`에서 `--repo`·`TVER_REPO` 지정 `log`를 확인했다. 설정이 없으면 `~/.tver/store`를 가리키고, 읽기 명령만으로는 이 폴더를 만들지 않는다.

## 엔진 3단계 · 저장 안전과 자동화 (R7·R11·R13)

- [x] 저장 전에 API 키 형태를 검사해 거부하고 오류·JSON 출력에서 값을 가린다(`src/tver/secrets.py`). `sk-…`·AWS·GitHub·Slack·Google 키, JWT, Bearer 토큰, 개인 키 머리글, 그리고 `apiKey`·`token`·`password`·`authorization` 같은 이름의 직접 입력값을 찾는다. 표현식(`={{ … }}`)과 credential 참조는 제외한다. diff·JSON·TUI·커밋 메시지에서도 가린다.
- [x] `--json` 출력 스키마와 diff 종료 코드 0/1/2, 모든 명령의 오류 코드 2를 적용한다.
- [x] 폴더 저장은 `*.json` 중 `nodes`·`connections`를 갖춘 워크플로우만 처리하고 나머지는 `skipped`로 센다. 숨김 파일과 하위 폴더는 보지 않고, 같은 저장 이름이 되는 두 파일은 두 번째를 `error`로 둔다.
- [x] 가짜 키·없는 파일·혼합 폴더에 대한 테스트를 추가한다(`tests/test_secrets.py`, `tests/test_folder_restore_json.py`).

확인: `uv run pytest -q`; `tver diff a a` → 0, `tver diff a b` → 1, 없는 파일 → 2; 가짜 키 저장 거부 및 원문 미노출.

결과(2026-10-28): 직접 실행해 같음 0, 다름 1, 없는 파일 2, 사용법 오류 2를 확인했다. 가짜 `sk-…` 키가 든 파일은 `refused … sk-…(32 chars)`로 거부되고(종료 2), 버전 수는 그대로이며 git 이력 전체에 원문이 없다. 혼합 폴더는 워크플로우만 `saved`이고 테스트 케이스 JSON과 메모는 `skipped`다.

## 엔진 4단계 · n8n 가져오기, 복원, 이름 변경 (R9·R10·R12)

- [x] `pull`은 n8n export 기능으로 현재 워크플로우를 읽어 각각 `save`한다. n8n에 쓰는 호출은 넣지 않는다. 보내는 명령은 `docker ps`(컨테이너 찾기)와 `docker exec <컨테이너> n8n export:workflow --all`(stdout 출력, 컨테이너 안에 파일을 쓰지 않음)뿐이다. 오프라인용 `--file`, 보관된 워크플로우 포함용 `--include-archived`가 있다.
- [x] 워크플로우 이름에서 안전한 파일 이름을 만들고 충돌을 구분한다. 이름이 겹치면 n8n id를 붙이고, id가 없으면 번호를 붙인다.
- [x] `restore`는 지정 revision을 출력 파일에 쓰되 저장소에 커밋하지 않는다. n8n에 가져올 수 있게 노드 위치를 다시 배치하고, 이미 있는 파일은 `--force` 없이 덮어쓰지 않는다. `-o -`는 stdout으로 쓴다.
- [x] 이름만 바뀐 노드의 삭제·추가 쌍을 `renamed` 하나로 합친다. 다른 노드의 `$('옛 이름')` 참조는 n8n처럼 새 이름으로 바꿔 비교한다. 옛 이름 참조가 남아 있으면 그 설정을 `still refers to the old name …` 표시와 함께 별도 변경으로 보여 준다.
- [x] 별도 시험 환경에서 pull의 읽기 전용 동작, restore의 버전 수 유지, 이름 변경 1개를 확인한다.

확인: `uv run pytest -q`; `tver restore <rev> <이름> -o <파일>` 후 해당 버전과 diff 0개; n8n 가져오기 전후 원본 상태 동일.

결과(2026-10-28): 테스트는 가짜 `docker` 실행 파일로 pull이 보낸 명령 전체를 기록해 export 외 호출이 없음을 확인한다. 실행 중인 n8n 컨테이너(`n8n`, compose 프로젝트 `day65-n8n`)에서도 임시 저장소로 `tver pull`을 실행했다. 결과는 `30 new version(s)`(refused 0)였고, 다시 실행하면 `0 new version(s)`였다. pull 전후 `n8n export:workflow --all` 출력의 SHA-256이 같았다. 실제 워크플로우가 든 임시 저장소는 확인 직후 지웠다. restore 결과 파일과 해당 버전의 diff는 0개이고 버전 수·HEAD·작업 트리는 그대로다. `Search FAQ` → `Find FAQ`(n8n식 참조 갱신 포함)는 `renamed` 1개다.

## 50분 목표와 남은 일

우선순위는 엔진 1 → 엔진 2 → TUI 1 → 설치였고, 이후 엔진 3·4까지 진행했다. R1~R14가 모두 구현·검증됐다(2026-10-28, `uv run pytest -q` 80 passed). 남은 한계는 `README.md`의 '한계' 절에 적었다.
