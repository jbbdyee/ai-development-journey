# tbench

HTTP 요청을 반복 측정하고, 터미널에서 진행 상황과 저장된 결과를 확인하는 도구입니다.

## 설치와 테스트

Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다. 이 저장소를 복제한 뒤 프로젝트 폴더에서 설치합니다.

```sh
cd AI/Workflow/tbench
uv tool install --editable .
tbench --help
uv run pytest -q
```

최종 공개 전 로컬 가짜 HTTP 서버로 실행한 전체 테스트 결과는 **27 passed**입니다. 테스트는 실제 n8n 웹훅이나 OpenAI API를 호출하지 않습니다.

## CLI 측정과 비교

아래 `requests/example.json`은 사용자가 준비한 JSON 본문 파일을 뜻합니다. 예제 파일은 저장소에 포함되지 않습니다. URL도 본인이 통제하는 테스트 서버 주소로 바꾸세요.

```sh
tbench http://127.0.0.1:8000/ --body-file requests/example.json -n 10 --plain
tbench http://127.0.0.1:8000/ --body-file requests/example.json -n 10 \
  --concurrency 3 --warmup 1 --max-p95 2 --max-failures 0 --plain
tbench compare before.json after.json
tbench history
tbench profile save example http://127.0.0.1:8000/ --body-file requests/example.json
tbench run example --plain
```

본문 파일을 주면 POST, 주지 않으면 GET으로 측정합니다. 성공 응답의 p50·p95·max와 실패 종류를 집계하고 첫 측정 호출을 별도로 표시합니다. 응답 JSON에 숫자형 `timings.*_ms`가 있으면 단계별 평균도 보여 줍니다. 기준 옵션을 지정하면 PASS/FAIL과 종료 코드 0/1을 반환합니다. 성공 응답이 0건이면 기준 판정은 FAIL입니다.

`--save <파일>`은 결과 JSON을 지정한 경로에 저장합니다. 지정하지 않으면 `~/.tbench/runs/`에 저장되어 `history`에 표시됩니다. `--log <파일>.jsonl`은 측정 호출마다 한 줄씩 기록합니다. 비교 명령은 p50·p95·max·실패 수의 변화율과 URL·본문 해시·N 차이 경고를 보여 줍니다.

## TUI에서 요청 고르기

```sh
tbench http://127.0.0.1:8000/ --pick-request --requests-dir requests -n 15
```

`--pick-request`는 측정 전에 `requests/*.json`을 보여 줍니다. 방향키로 고르고 Enter를 누르면 그 파일의 JSON이 POST 본문으로 전송됩니다. 빈 목록이나 잘못된 JSON이면 화면에 메시지를 보여 주고 측정하지 않습니다. 기본 요청 폴더는 실행 위치의 `requests`입니다. 파일 경로를 이미 알고 있다면 기존 `--body-file requests/example.json`을 사용하세요. 두 옵션은 함께 사용할 수 없으며 `--pick-request`는 TUI 전용입니다.

측정 화면의 `h`는 `~/.tbench/runs/` 기록을 최신순으로 보여 줍니다. 기록을 선택해 Enter를 누르면 그 결과를 비교 기준으로 가져옵니다. `c`는 비교 화면을 바로 엽니다. 결과 두 개를 Enter로 선택하면 p50·p95·max·실패 수와 변화율이 나오고 URL·본문 해시·N이 다르면 경고가 표시됩니다. `Esc`는 이전 화면, `q`는 종료입니다. `--save`로 별도 경로에 저장한 파일은 TUI 기록 목록에 나오지 않습니다.

66일차 `turl` 수업 자료는 요청과 응답을 함께 담는 `history.json` 형식을 설명하지만, 현재 실제 저장 파일은 없어 호환 스키마를 확인하지 못했습니다. `turl` 기록을 쓰려면 요청의 Body JSON만 확인해 `requests/<이름>.json`으로 따로 저장하세요. 기록 전체나 헤더를 본문 파일로 복사하지 마세요.

## 주의사항

- 측정은 대상 URL에 실제 HTTP 요청을 보냅니다. 유료 API를 호출하는 웹훅을 지정하면 비용이 발생할 수 있습니다. 자동 테스트는 로컬 가짜 서버만 사용합니다.
- 저장 결과에는 요청 본문 대신 SHA-256 해시가 들어가고 인증·키 성격의 머리글 값은 가려집니다. URL 자체는 결과에 저장되므로 URL에 비밀값을 넣지 마세요. 프로필은 URL의 사용자 정보·쿼리·fragment를 거부하며, 본문 파일의 절대 경로를 저장하므로 파일을 이동하면 다시 실행할 수 없습니다.
- TUI 기록과 비교 화면은 기본 폴더 `~/.tbench/runs/`의 결과를 사용합니다. `--save`로 다른 경로에 저장한 파일은 CLI `compare`로 비교하세요.

가짜 서버로 블로그 화면을 찍을 때는 해당 서버 URL을 위 명령의 URL 자리에 넣고 `-n 15`로 실행합니다. 첫 화면에서 요청을 고른 뒤 결과 행과 스파크라인이 늘어나는 동안 캡처하고, 측정 완료 후 `q`로 저장한 실행 두 개를 준비해 `h`와 비교 화면을 캡처할 수 있습니다.
