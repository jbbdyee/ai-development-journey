# tver

**n8n 워크플로우 JSON의 의미 있는 변경만 노드별로 비교하고, 정리한 워크플로우를 별도 git 저장소에 버전으로 남기는 Python CLI/TUI 도구입니다.**

## 만든 이유

n8n에서 노드를 옆으로 옮기기만 해도 내보낸 JSON이 바뀝니다. 그래서 일반 `diff`나 git 이력으로는 무엇이 실제로 바뀌었는지 읽기 어렵습니다. `tver`는 위치·식별자·순서 같은 뜻 없는 차이를 빼고 노드 이름으로 짝지어 비교합니다. 변경은 **모델·지시문·흐름** 세 종류로 나눠 한 줄로 요약합니다. 저장할 때도 같은 규칙을 적용하므로, 내용이 같으면 버전이 늘지 않습니다.

## 주요 기능

- **의미 기반 비교:** 노드 추가·삭제, 설정의 점 경로(`parameters.model.value`)별 전후 값, 연결 추가·삭제를 보여 줍니다. 80자를 넘거나 여러 줄인 지시문은 `+`/`-` 줄 차이로 보여 줍니다.
- **세 종류 요약:** `7 change(s) · model 1 · prompt 1 · flow 5`
- **버전 저장:** `save`는 정리한 JSON을 별도 git 저장소에 커밋하고, 직전 버전 대비 요약을 커밋 메시지에 넣습니다. 변경이 없으면 `no change`로 끝납니다. 폴더를 주면 워크플로우 JSON만 저장합니다.
- **목록·버전 비교·복원:** `log`, `diff REV1 REV2 이름`, `restore REV 이름 -o 파일`. 복원은 파일만 쓰고 저장소와 n8n은 건드리지 않습니다.
- **n8n 일괄 가져오기:** `pull`은 실행 중인 n8n 컨테이너에서 `n8n export:workflow --all`만 실행해 읽습니다. n8n에는 아무것도 쓰지 않습니다.
- **비밀값 차단:** API 키처럼 보이는 값이 있으면 저장을 거부합니다. 경고·diff·JSON 출력에서도 원문을 가립니다(`sk-…(32 chars)`).
- **이름 변경 감지:** 이름만 바뀐 노드는 삭제+추가가 아니라 `renamed` 하나로 보여 줍니다.
- **자동화용:** `--json` 출력과 종료 코드(diff: 같음 0·다름 1·오류 2, 다른 명령: 오류 2)를 제공합니다.
- **TUI:** 왼쪽 버전 목록, 오른쪽 노드별 변경 트리, 아래 선택한 변경의 전후 값·줄 차이를 보여 줍니다. `s`로 현재 파일을 저장합니다.

## 설치

Python 3.11 이상, git, [uv](https://docs.astral.sh/uv/)가 필요합니다. `pull`에는 docker가 필요합니다.

```sh
git clone https://github.com/jbbdyee/ai-development-journey.git
cd ai-development-journey/AI/Workflow/tver
uv tool install --editable .
tver --help
```

개발 환경에서는 `uv run tver ...`도 쓸 수 있습니다.

## 버전 저장소

| 우선순위 | 지정 방법 |
| --- | --- |
| 1 | `--repo 경로` (명령 앞이나 뒤) |
| 2 | 환경 변수 `TVER_REPO` |
| 3 | 기본값 `~/.tver/store` |

저장소는 첫 저장 때 만들어집니다. 표식은 `.git/tver-store`에 있습니다. 표식이 없고 비어 있지 않은 폴더는 저장소로 쓰지 않으므로, 다른 git 저장소를 실수로 지정해도 커밋하지 않습니다. 한 워크플로우의 모든 버전은 `<이름>.json` 파일 하나의 이력으로 쌓입니다. 이름은 공백·슬래시·기호를 `-`로 바꾼 소문자이며, 한글은 그대로 둡니다.

## CLI 사용

```sh
# 두 파일 비교 (같으면 0, 다르면 1, 오류면 2)
tver diff helpdesk-v1.json helpdesk-v2.json

# 버전 저장: 같은 이름(-n)으로 저장하면 한 워크플로우의 버전이 쌓인다
tver save helpdesk-v1.json -n helpdesk
tver save helpdesk-v2.json -n helpdesk
tver save helpdesk-v2.json -n helpdesk      # → no change, 커밋하지 않음

# 폴더: 워크플로우 JSON만 저장, 나머지는 skipped
tver save my-work/

# 목록과 저장된 두 버전 비교
tver log                     # 저장된 워크플로우와 버전 수
tver log helpdesk            # 해시 · 시각 · 작성자 · 요약
tver diff 1a2b3c4 5d6e7f8 helpdesk

# 예전 버전을 파일로 꺼내기 (n8n 적용은 사람이 직접)
tver restore 1a2b3c4 helpdesk -o helpdesk-restored.json

# 실행 중인 n8n의 모든 워크플로우를 버전으로 남기기 (읽기 전용)
tver pull                          # compose 서비스 'n8n' 컨테이너를 찾음
tver pull --container my-n8n
tver pull --file all-workflows.json

# 프로그램용 출력
tver --json diff helpdesk-v1.json helpdesk-v2.json
```

`diff` 출력 예(기준 자료 v1 → v2):

```
~ Answer  parameters.options.systemMessage  [prompt]
      You are the company IT help desk. Answer in Korean in at most 3 sente…
    + When the answer comes from a FAQ entry, end with its id in brackets, for example [FAQ-003]. Keep answers short.
~ Answer model  parameters.model.value: "gpt-4.1-mini" → "gpt-5.4-nano"  [model]
~ Question webhook  parameters.path: "rel-v1" → "rel-v2"  [flow]
+ node  Review check (code)  [flow]
- link  Answer → Build result (main)  [flow]
+ link  Answer → Review check (main)  [flow]
+ link  Review check → Build result (main)  [flow]

7 change(s) · model 1 · prompt 1 · flow 5
```

### 비교 규칙

- **비교에서 빼는 값:**
  - 노드의 `id`·`position`·`webhookId`
  - 워크플로우의 `id`·`versionId`·`updatedAt`·`meta`·`pinData`·`tags`·`active` 등 내보내기 정보
  - 노드·키의 순서와 최상위 `name`
- **연결:** 보내는 노드·출력 종류/번호·받는 노드·입력 종류/번호의 집합으로 비교합니다.
- **분류:**
  - `model`: `lmChat…` 노드의 `parameters.model`
  - `prompt`: `agent` 노드의 `parameters.text`·`parameters.options.systemMessage`, `code` 노드의 `parameters.jsCode`
  - `flow`: 나머지 설정, 노드 추가·삭제, 연결, 이름 변경

## TUI 사용

```sh
tver helpdesk.json -n helpdesk
```

| 키 | 동작 |
| --- | --- |
| `↑` `↓` | 버전·변경 이동 |
| `Enter` | 버전 목록 → 변경 트리로 초점 이동 |
| `Tab` | 패널 이동 |
| `s` | 현재 파일 저장 (변경 없으면 `no change`, 비밀값이 있으면 거부) |
| `r` | 다시 읽기 |
| `q` | 종료 |

버전을 고르면 직전 버전과 비교한 변경 트리가 나타납니다. 첫 버전은 빈 워크플로우와 비교합니다. 아래 상태 줄은 현재 파일이 최신 버전과 어떻게 다른지 보여 줍니다. 화면에는 커밋 작성자를 표시하지 않습니다.

## 검증과 한계

`uv run pytest -q`로 테스트 80개가 통과합니다. 모든 테스트는 임시 `HOME`과 임시 저장소를 쓰고, n8n은 호출을 기록하는 가짜 `docker`로 대신합니다. 요구사항별 확인 근거는 [Doc/SPEC.md](Doc/SPEC.md) §7에, 단계별 진행은 [Doc/IMP-PLAN.md](Doc/IMP-PLAN.md)에 있습니다.

한계:

- **비밀값 탐지:** 알려진 키 형태와 비밀 이름 필드만 찾습니다. 임의의 이름 필드에 든 형식 없는 토큰은 놓칠 수 있습니다. 반대로 `password` 같은 이름의 긴 일반 문자열은 비밀값으로 보고 거부할 수 있습니다.
- **복원 파일:** 노드 id·webhookId를 넣지 않아 n8n이 가져올 때 새로 만듭니다. 웹훅 경로(`parameters.path`)는 그대로 유지됩니다. 노드 위치는 단순 자동 배치입니다.
- **pull:** docker 안의 n8n만 지원합니다. n8n REST API 방식은 없습니다.
- **이름 변경 감지:** 이름 외 모든 값이 같은 경우만 짝짓습니다. 이름과 설정을 함께 바꾸면 삭제+추가로 보입니다.
- **원격과 동시성:** 원격 git 동기화와 동시 저장 병합은 범위 밖입니다.
