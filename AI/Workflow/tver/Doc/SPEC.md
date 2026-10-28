# tver SPEC

## 1. 목적과 범위

`tver`는 n8n 워크플로우 JSON의 의미 있는 변경을 비교하고, 정리한 워크플로우를 별도 git 저장소에 버전으로 남기는 터미널 도구다. CLI와 TUI가 같은 비교·저장 엔진을 사용한다. n8n에는 쓰지 않는다.

## 2. 확인할 수 있는 요구

| 번호 | 요구 | 요청의 말 | 확인 방법 | 우선순위 |
| --- | --- | --- | --- | --- |
| R1 | `tver diff a.json b.json`은 노드를 `name`으로 짝짓고 추가·삭제 노드, 변경된 설정의 점 경로와 전후 값, 추가·삭제 연결을 표시한다. | ① | `reference/helpdesk-v1.json` → `v2.json`에서 변경 7개를 표시한다. | 꼭 |
| R2 | `id`, `position`, `webhookId`, `versionId`, `updatedAt` 같은 내보내기 메타데이터와 노드·객체 키 순서를 비교에서 제외한다. | ② | 위치·id·노드 순서·키 순서만 바꾼 사본은 변경 0개다. | 꼭 |
| R3 | 80자를 넘거나 여러 줄인 문자열의 변경은 `+`·`-`가 붙은 줄 단위 차이로 보여 준다. | ③ | v1 → v2 `systemMessage`의 `[FAQ-003]` 추가 줄을 볼 수 있다. | 꼭 |
| R4 | 모든 변경을 `model`, `prompt`, `flow`로 분류해 합계와 함께 한 줄로 표시한다. | ④ | v1 → v2 결과는 `7 change(s) · model 1 · prompt 1 · flow 5`다. | 꼭 |
| R5 | `tver save <파일>`은 정리한 JSON을 별도 git 저장소에 커밋하고 직전 버전 대비 변경 요약을 메시지에 넣는다. 의미 있는 변경이 없으면 커밋하지 않는다. | ⑤ | 같은 파일을 두 번 저장하거나 위치만 바꿔 다시 저장해도 버전은 1개이며 `no change`를 표시한다. | 꼭 |
| R6 | `tver log <이름>`은 커밋·시각·요약을 보여 주고, `tver diff <rev1> <rev2> <이름>`은 저장된 임의의 두 버전을 비교한다. | ⑥ | 두 차례 다른 내용을 저장하면 목록 2줄, 버전 비교 결과는 R1·R4와 같은 형식이다. | 꼭 |
| R7 | API 키처럼 보이는 값이 있으면 저장을 거부하고 출력에서 원문을 가린다. | ⑦ | 가짜 `sk-…` 값을 넣고 저장하면 버전 수가 늘지 않고 출력에 원문이 없다. | 나중 |
| R8 | `tver <파일>` TUI는 왼쪽 버전 목록, 오른쪽 선택 버전과 직전 버전의 노드별 변경 트리, 아래 선택 변경의 전후 내용·줄 차이를 보여 준다. `[s]`로 현재 파일을 저장한다. | ⑧ | 두 버전이 있는 저장소에서 목록·트리·상세를 볼 수 있고 `[s]` 뒤 새 변경이 있으면 목록이 한 줄 늘어난다. | 꼭 |
| R9 | `tver pull`은 실행 중인 n8n의 모든 워크플로우를 가져와 각각 저장하며 n8n에 쓰지 않는다. | ⑨·끝 | 별도 시험 환경에서 `N new version(s)`를 보고 가져오기 전후 n8n 상태가 같다. | 나중 |
| R10 | `tver restore <rev> <이름> -o <파일>`은 해당 버전을 파일로 꺼내고 저장소는 변경하지 않는다. | ⑩ | 꺼낸 파일과 해당 버전의 차이가 0개이며 `log` 버전 수가 그대로다. | 나중 |
| R11 | `--json`으로 결과를 기계가 읽을 수 있게 하고 diff 종료 코드는 같음 0, 다름 1, 오류 2로 한다. 다른 명령의 오류도 2다. | ⑪ | 같은 파일 비교 0, 다른 파일 비교 1, 없는 파일 비교 2; `--json` 출력은 JSON 파서로 읽힌다. | 나중 |
| R12 | 이름 외 종류·설정이 동일한 미짝짓기 노드의 삭제·추가를 이름 변경 하나로 표시한다. | ⑫ | `Search FAQ`만 `Find FAQ`로 바꾼 파일(n8n 편집기처럼 다른 노드의 `$('Search FAQ')` 참조도 함께 바뀐 파일)은 `renamed` 1개다. | 나중 |
| R13 | `tver save <폴더>`는 `*.json` 중 `nodes`와 `connections`를 가진 워크플로우만 저장한다. | 끝: 폴더 | 워크플로우·테스트 케이스·메모가 섞인 폴더에서 워크플로우만 저장하고 나머지는 `skipped`다. | 나중 |
| R14 | `uv tool install`로 `tver` 명령을 설치하며 기본 저장소는 `~/.tver/store`, `--repo`와 `TVER_REPO`로 바꿀 수 있다. | 첫 문단·끝 | 설치 뒤 다른 폴더에서 `tver --help`가 실행되고 `uv tool list`에 `tver`가 나온다. | 꼭 |

## 3. 숨은 요구

- 저장할 때도 비교와 같은 정리 규칙을 적용하고 키 순서가 일정한 JSON으로 기록한다. 변경 없음 판정은 정리된 내용에 대해 한다.
- 분류 기준을 고정한다. Chat model 노드의 `parameters.model`은 `model`, Agent의 `systemMessage`·`text`와 Code의 `jsCode`는 `prompt`, 다른 설정과 연결은 `flow`다.
- n8n 이름을 파일 이름으로 쓸 때 공백·슬래시·한글을 안전한 소문자 이름으로 바꾼다. 동명이인 충돌도 피해야 한다.
- 엔진은 TUI 없이 호출할 수 있어야 한다. CLI, TUI, 테스트가 같은 변경 목록을 사용한다.
- 테스트 저장소는 임시 디렉터리에 둔다. 실제 `~/.tver/store`와 n8n을 테스트에서 변경하지 않는다.
- 설치 가능한 패키지의 `[project.scripts]`에 `tver` 진입점을 등록한다.

## 4. 범위 밖

- n8n에 자동으로 올리기, 배포·되돌리기 실행
- 원격 git 서버 동기화, 동시 저장의 병합
- Credential 비밀값 자체의 취급이나 출력

## 5. 구현 전에 정할 계약

| 항목 | 결정 |
| --- | --- |
| 노드 짝짓기 | 우선 `name`; 이름 변경 후보는 R12에서 별도 처리 |
| 비교 제외 | 내보내기 메타데이터와 화면 배치값; 실제 노드 설정·연결은 유지 |
| 연결 비교 | 보내는 노드·출력 종류/인덱스·받는 노드·입력 종류/인덱스로 정규화해 집합 비교 |
| 긴 값 | 80자 초과 또는 줄바꿈이 있으면 줄 단위 차이 |
| 정리 형식 | 노드는 이름순, 모든 객체 키는 알파벳순. 노드의 `id`·`position`·`webhookId`와 워크플로우의 `id`·`versionId`·`updatedAt`·`createdAt`·`meta`·`pinData`·`tags`·`active`·`staticData` 등을 뺀다. 연결은 n8n 형식을 유지하되 같은 출력 칸의 대상은 정렬·중복 제거한다. 다시 정리해도 결과가 같다. |
| 비교 단위 | 설정은 점 경로(`parameters.model.value`, 목록은 `[0]`)의 말단 값마다 1개. 매개변수 안 목록의 순서는 의미가 있으므로 유지한다. 빈 객체·빈 목록과 키 없음은 같게 본다. |
| 워크플로우 수준 | 최상위 `name`은 워크플로우를 가리키는 이름이라 비교하지 않는다. `settings` 등 나머지 최상위 값의 변경은 `(workflow)` 노드의 `flow` 변경이다. |
| 분류 상세 | `model`: 종류가 `lmChat…`인 노드의 `parameters.model` 및 하위 경로. `prompt`: `agent` 노드의 `parameters.text`·`parameters.options.systemMessage`, `code` 노드의 `parameters.jsCode`. 노드 추가·삭제와 연결은 모두 `flow`. |
| 저장소 | 기본 `~/.tver/store`; 명시적 `--repo`가 `TVER_REPO`보다 우선 |
| 저장 이름 | `tver save <파일> [-n 이름]`. 이름을 안 주면 파일 이름을 쓴다. 안전한 소문자 이름(공백·슬래시·기호 → `-`, 한글 유지, `.json` 제거)으로 바꿔 저장소 최상위 `<이름>.json` 하나에 한 워크플로우의 모든 버전을 쌓는다. `log`·버전 `diff`의 이름도 같은 규칙으로 바꾼다. |
| 저장 판정 | 직전 저장본과 `compare()` 결과가 0개면 커밋하지 않고 `no change`를 출력한다(종료 코드 0). 첫 저장의 메시지는 `<이름>: first version · N node(s)`, 이후는 `<이름>: <요약 한 줄>`과 변경 목록 본문이다. |
| 저장소 보호 | 저장소 표식은 `.git/tver-store`에 두어 이력에는 워크플로우 버전 커밋만 남는다. 표식이 없고 비어 있지 않은 폴더는 저장소로 쓰지 않는다(다른 git 저장소 오염 방지). 커밋 작성자는 사용자의 전역 git 이름·이메일, 없으면 `tver`다. 바깥의 `GIT_DIR` 등 환경 변수는 무시한다. |
| TUI | `tver [--repo 저장소] <파일> [-n 이름]`. 이름 규칙은 `save`와 같다. 키: `↑↓` 이동, `Enter` 버전 → 변경 트리로 초점 이동, `Tab` 패널 이동, `s` 현재 파일 저장, `r` 다시 읽기, `q` 종료. 화면에는 커밋 작성자를 표시하지 않는다. |
| 버전 지정 | `tver diff REV1 REV2 이름`의 REV는 `tver log`에 나온 커밋 해시나 git이 아는 revision이다. |
| 명령 | `diff`, `save`(파일·폴더), `log`, `restore`, `pull`, 파일을 인수로 받은 TUI. 공통 옵션은 `--repo`, `--json`(명령 앞이나 뒤 모두 가능) |
| 종료 코드 | `diff`: 같음 0, 다름 1, 오류 2. 다른 명령: 성공 0, 오류 2(사용법 오류 포함). 폴더 저장·pull은 `refused`·`error` 항목이 하나라도 있으면 2, `skipped`만 있으면 0. 저장 거부(비밀값)도 2. |
| JSON 출력 | `diff`: `old`·`new`·`changed`·`total`·`counts`·`summary`·`changes[]`(`op`·`node`·`category`·`key`·`before`·`after`·`lines`·`note`). `save` 파일: `file`·`status`·`detail`·`name`·`rev`·`versions`. 폴더·`pull`: `counts`·`entries[]`(+`pull`은 `new_versions`). `log`: `versions[]`(`rev`·`time`·`author`·`subject`·`summary`). 오류: `{"error": …}`를 stdout에 출력. |
| 보안 | 저장(`save`·폴더·`pull`·TUI `s`) 전에 비밀값을 검사해 하나라도 있으면 아무것도 쓰지 않고 거부한다. 탐지는 키 형태 패턴(`sk-…`, AWS, GitHub, Slack, Google, JWT, Bearer, 개인 키)과 비밀 이름 필드(`apiKey`·`token`·`secret`·`password`·`authorization` 등, `{name, value}` 쌍 포함)의 직접 입력값(8자 이상, 표현식 아님)이다. 노드의 `credentials` 참조는 제외한다. 출력에는 앞 3자와 길이만 보인다(`sk-…(32 chars)`). diff 출력에서는 패턴은 그 부분만, 비밀 이름 필드는 값 전체를 가린다. |
| 이름 변경 | 짝이 없는 삭제·추가 노드 중 다른 노드의 옛 이름 참조(`$('X')`, `$("X")`, `$node['X']`, `$items('X'…`)를 새 이름으로 바꿨을 때 이름 외 모든 값이 같으면 `renamed`(flow)다. 연결과 참조는 새 이름 기준으로 비교한다. 옛 이름 참조가 남은 설정은 `note`가 붙은 변경으로 따로 보인다. 일대일로만 짝짓는다. |
| pull | `docker ps --filter label=com.docker.compose.service=n8n`으로 컨테이너를 하나 찾는다(`--container`, `TVER_N8N_CONTAINER`가 우선). 그다음 `docker exec <c> n8n export:workflow --all`의 stdout만 읽는다. 보관된(`isArchived`) 워크플로우는 `--include-archived` 없이는 `skipped`다. 저장 이름은 워크플로우 이름의 안전한 이름이고, 겹치면 `-<n8n id>`를 붙인다. |
| restore | 정리된 저장본에 자동 배치 위치를 다시 넣어 파일로 쓴다. 저장소에는 아무것도 하지 않는다. 기존 파일은 `--force`가 있어야 덮어쓴다. `-o -`는 stdout으로 쓴다. 노드 id·webhookId는 넣지 않으므로 n8n 가져오기 때 새로 생긴다. |
| 폴더 저장 | 폴더 바로 아래 파일만 본다(숨김 파일·하위 폴더 제외). `.json`이 아니거나, 읽을 수 없거나, `nodes` 목록과 `connections` 객체가 없으면 `skipped`다. 저장 이름은 파일 이름이다. |

## 6. VIBE-Q와 비교

- 요청의 ①~⑫와 마지막 두 부탁을 모두 반영했다. R14는 첫 문단의 ‘어느 폴더에서나’와 별도 저장소 요구에서 분리했다.
- 추가로 정리한 저장 형식, 분류 규칙, 안전한 파일 이름, 엔진·TUI 분리, 테스트 격리, 설치 진입점을 숨은 요구로 기록했다.
- `R7`은 원문에선 중요한 안전 요구지만 50분 목표에서는 후속 단계다. 구현 전에는 실제 비밀값 파일을 저장하지 않는 운영 제약을 둔다.

## 7. 구현·검증 상태 (2026-10-28)

| 번호 | 상태 | 근거 |
| --- | --- | --- |
| R1 | 완료 | v1 → v2 7개 (`tests/test_engine.py`, `tests/test_cli.py`, 직접 실행) |
| R2 | 완료 | `helpdesk-v1-moved.json`·무작위 섞기 5회 → 0개 |
| R3 | 완료 | `systemMessage`의 `+ … [FAQ-003] …` 한 줄 |
| R4 | 완료 | `7 change(s) · model 1 · prompt 1 · flow 5` |
| R5 | 완료 | 같은 파일·위치만 바꾼 사본 재저장 시 `no change`, `git rev-list --count` 불변 |
| R6 | 완료 | `log` 2줄, revision diff가 파일 diff와 같음 |
| R7 | 완료 | 가짜 키 저장 거부, 버전 수 불변, 출력·git 이력에 원문 없음 (`tests/test_secrets.py`) |
| R8 | 완료 | Textual `run_test`로 목록·트리·상세·`s` 확인 (`tests/test_tui.py`), 캡처 3 |
| R9 | 완료 | 가짜 docker로 호출 명령 검증, 실제 n8n에서 read-only pull: 30개 저장·재실행 0개, export 해시 전후 동일 |
| R10 | 완료 | 복원 파일과 해당 버전 diff 0개, 버전 수·HEAD·작업 트리 불변 |
| R11 | 완료 | 같음 0·다름 1·없는 파일 2, `--json`은 `json.loads`로 읽힘 |
| R12 | 완료 | `Search FAQ` → `Find FAQ` = `renamed` 1개 (`tests/test_rename.py`) |
| R13 | 완료 | 혼합 폴더에서 워크플로우만 `saved`, 나머지 `skipped` |
| R14 | 완료 | `uv tool install --editable .`, `uv tool list`에 `tver`, `/tmp`에서 `tver --help` |
