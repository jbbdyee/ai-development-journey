# tscan 구현 계획

기준 문서: `Doc/TODO.md`, `Doc/SPEC.md`.
원칙: **엔진(백엔드)을 먼저 완성하고, 화면(TUI)은 나중에 올린다.** 화면 없이 엔진만으로 테스트(`pytest`, `--plain`, `staged`)가 완전히 통과되어야 한다.
체크(`- [x]`)는 구현과 확인 명령이 모두 성공적으로 끝난 뒤에만 표시하고 커밋한다.

---

## 엔진 1단계 · 찾고 가리기 (R1 · R2 · R3 · R4 · R13)

- [x] `pyproject.toml` 기본 프로젝트 설정 (`argparse`, `textual` 의존성 포함) 및 패키지 구조(`src/tscan/`) 구성
- [x] `patterns.py`: API 키(`sk-…`), 주민등록번호, 전화번호, 이메일 정규식 및 경계 조건(`(?<![0-9a-zA-Z.])`, `(?![0-9a-zA-Z.])`) 정의
- [x] `masker.py`: 종류별 마스킹 함수 구현 (`sk-…****…a9`, `010-****-2135`, `y***@example.com`, `900101-*******`)
- [x] `models.py`: `Finding(kind, path, line, masked, preview)` 데이터 클래스 정의 (원래 비밀값 필드는 아예 두지 않음)
- [x] `scanner.py`: `scan_text(text, path, env_values)` 구현 (한 줄씩 검사하여 탐지 즉시 마스킹 생성)
- [x] `scanner.py`: `scan_folder(path)` 구현
  - 건너뛰기 필터링: `.git`, `node_modules`, `.venv`, 1MB 초과 파일, 바이너리(NUL 바이트 포함) 건너뛰기 및 건너뛴 수 집계
  - `.env` 파싱: 프로젝트 내 `.env`에서 6자 이상 값 추출하여 `env_value` 검사에 사용
- [x] `cli.py`: `tscan scan <folder> --plain` CLI 엔트리포인트 구현
- [x] `tests/test_engine.py`: 임시 폴더(`tmp_path`)에서 가짜 비밀을 런타임에 동적으로 조립하여 테스트
  - 찾아야 할 것(4종류 비밀, `.env` 값) 탐지 검증
  - 찾으면 안 되는 것(날짜 `2026-10-27`, 버전 `1.0.10`, 주문번호 `202610271234`) 0건 검증
  - 건너뛰기 대상(대용량 파일, 바이너리) 건너뜀 검증
  - 원문 비밀값이 출력 결과 및 Finding 모델에 존재하지 않는지 검증

확인:
```bash
uv run pytest -q
mkdir -p /tmp/fake && printf 'key=sk-test-%s\ncall 010-0000-0000\ndate 2026-10-27\n' abcdefghijklmnopqrst > /tmp/fake/a.txt
uv run tscan scan /tmp/fake --plain
# R1, R2, R4 확인: 키·전화 찾고, 날짜는 안 찾음, 값은 가려짐
uv run tscan scan /tmp/fake --plain | grep -c abcdefghijklmnopqrst
# R2 확인: 원문 검색 결과 0
rm -rf /tmp/fake
```

---

## 엔진 2단계 · 커밋 전에 막기 (R5 · R6)

- [x] `git.py`: `get_staged_files()` 구현 (`git diff --cached --name-only --diff-filter=ACM`)
- [x] `git.py`: `get_staged_bytes(rel_path)` 및 `scan_staged()` 구현 (`git show :<path>`)
- [x] `cli.py`: `tscan staged` 서브커맨드 구현
  - 스테이징된 내용만 스캔
  - 탐지된 비밀이 있으면 가린 목록 출력 후 **종료 코드 1** 반환
  - 없으면 **종료 코드 0** 반환
- [x] `hooks.py`: `install_hook()` / `uninstall_hook()` 구현
  - `.git/hooks/pre-commit` 파일 설치 및 `chmod +x` 부여
  - `# Managed by tscan` 서명 주석 포함
  - 기존 타사 훅이 존재하고 tscan 서명이 없으면 덮어쓰지 않고 에러 안내 및 중단
  - `uninstall-hook` 시 tscan 서명이 있는 훅만 안전하게 제거
- [x] `cli.py`: `tscan install-hook` / `tscan uninstall-hook` 서브커맨드 연동
- [x] `tests/test_git_hook.py`: 임시 git 저장소를 생성하여 staged 검사 및 훅 동작 테스트

확인:
```bash
uv run pytest -q
mkdir -p /tmp/fake-git && cd /tmp/fake-git && git init -q
printf 'key=sk-test-%s\n' abcdefghijklmnopqrst > safe.txt
git add safe.txt
uv run tscan staged; echo "staged exit code: $?" # 결과: 1
git rm --cached safe.txt > /dev/null
uv run tscan staged; echo "staged exit code: $?" # 결과: 0
uv run tscan install-hook
ls -la .git/hooks/pre-commit
uv run tscan uninstall-hook
cd <tscan 프로젝트 경로> && rm -rf /tmp/fake-git
```

---

## TUI 1단계 · 목록 및 미리 보기 (R8)

- [x] `app.py`: Textual App(`TScanApp`) 구현
- [x] 메인 레이아웃: 상단 헤더, 탐지 목록 DataTable (종류, 파일, 줄, 가린 값), 하단 미리 보기 패널, 상태 바 (단축키 안내)
- [x] 스캔 로직을 Textual `run_worker(..., thread=True)` 백그라운드 워커로 실행하여 UI 프리징 방지
- [x] 목록에서 항목 커서 이동 시 해당 파일의 앞뒤 2줄 문맥(총 5줄)을 가져와 하단에 표시
  - **핵심:** 미리 보기 문맥 안의 다른 줄에 포함된 비밀도 동일하게 마스킹 처리하여 렌더링
- [x] `[q]` 단축키로 종료 기능 구현

확인:
```bash
uv run pytest -q
mkdir -p /tmp/fake-tui && printf 'intro\nkey=sk-test-%s\ncall 010-1234-5678\nend\n' abcdefghijklmnopqrst > /tmp/fake-tui/leak.txt
uv run tscan /tmp/fake-tui
# TUI 화면에서 표에 2건 표시, 커서 이동 시 미리 보기 확인, 값 마스킹 확인, q로 정상 종료
rm -rf /tmp/fake-tui
```

---

## 설치 · 어느 폴더에서나 사용 (R14)

- [x] `pyproject.toml`에 `[project.scripts]`의 `tscan = "tscan.cli:main"` 엔트리포인트 등록 확인
- [x] `uv tool install --editable .` 실행으로 로컬 CLI 도구 등록
- [x] `which tscan` 및 `uv tool list`에서 `tscan` 등록 상태 확인
- [x] 다른 디렉터리(`/tmp`)에서 `tscan --help` 및 `tscan scan . --plain` 동작 검증

확인:
```bash
uv tool install --editable .
uv tool list
which tscan
cd /tmp && tscan --help
cd <tscan 프로젝트 경로>
```

---

## 엔진 3단계 · 무시 · JSON · 요약 (R7 · R10 · R12)

- [x] `ignore.py`: `.tscanignore` 파서 구현
  - `path:line` 매칭
  - `kind:path` 매칭
  - 경로 글롭(glob) 패턴 매칭
- [x] `scanner.py`: 스캔 시 `.tscanignore` 규칙 반영하여 무시 대상 필터링
- [x] `cli.py`: `--json` 출력 옵션 추가 (마스킹된 값 포함 JSON 구조 출력, 표준 종료 코드 0/1/2 반환)
- [x] `cli.py`: `--summary` 플래그 추가 (종류별/파일별 카운트 및 건너뛴 파일 통계 요약표 출력)
- [x] `tests/test_ignore_json.py`: 무시 규칙, JSON 포맷 및 종료 코드, 요약 카운트 단위 테스트 작성

확인:
```bash
uv run pytest -q
uv run tscan scan . --json | python -m json.tool
echo "JSON exit code: $?"
uv run tscan scan . --plain --summary
```

---

## 엔진 4단계 · 기록 · 사용자 모양 (R9 · R11)

- [x] `history.py`: `scan_history()` 구현 (`git log -p` 커밋별 diff 중 추가된 `+` 줄을 분석하여 과거 커밋 해시, 파일, 종류 추출)
- [x] `cli.py`: `tscan history` 서브커맨드 구현
- [x] `config.py`: `.tscan.toml` 및 `~/.tscan/rules.toml` TOML 파서 구현 (`[[rules]] name="...", pattern="..."`)
- [x] `scanner.py`: 사용자 정의 패턴을 기본 패턴 세트에 병합하여 스캔
- [x] `tests/test_history_config.py`: 과거 커밋 탐지 및 커스텀 사번(`E-\d{6}`) 패턴 탐지 테스트

확인:
```bash
uv run pytest -q
uv run tscan history
```

---

## TUI 2단계 · [i] 무시 등록 및 재검사 (R7 · R8)

- [x] TUI 목록에서 선택한 항목을 `.tscanignore`에 바로 추가하는 `[i]` 키 바인딩 구현
- [x] 무시 항목 추가 후 즉시 재스캔을 트리거하여 목록 갱신 (`[r]` 키로도 수동 재검사 가능)
- [x] 무시 등록 완료 토스트 메시지 또는 상태 바 알림 표시

확인:
```bash
uv run tscan <테스트폴더>
# [i] 입력 시 .tscanignore 생성/추가 및 목록에서 제외되는지 인터랙티브 확인
```

---

## 진행 및 커밋 원칙

1. **단계별 독립 검증:** 각 단계(엔진 1단계 → 엔진 2단계 → TUI 1단계 → 설치 ...)마다 체크리스트 항목을 구현하고 명시된 확인 명령을 직접 실행한다.
2. **테스트 가짜 데이터 원칙:** 테스트 코드 작성 시 `"sk-" + "test-" + "a" * 20`와 같이 동적 문자열 연결 방식을 사용하여 소스 코드 파일 자체가 `tscan`의 탐지 대상이 되지 않도록 한다.
3. **완료 후 체크 및 커밋:** 각 단계의 확인이 끝날 때마다 IMP-PLAN의 체크박스(`- [x]`)를 갱신하고 `git commit -m "<단계명>"` 커밋을 진행한다.

---

## 전체 구현 및 최종 검증 기록 (2026-10-27)

- **전체 요구사항 (R1~R14) 구현 완료:**
  - R1 (다양한 비밀 패턴 탐지): API 키, 전화번호, 이메일, 주민등록번호 지원
  - R2 (안전한 마스킹 및 Zero-Retention): 결과 객체 내 원문 배제 및 CLI/TUI/미리 보기 전역 마스킹
  - R3 (.env 값 탐지): 6자 이상 설정값을 인메모리 비교하여 타 파일 복사 탐지 (`env_value`)
  - R4 (오탐 방지): 날짜(`2026-10-27`), 버전(`1.0.10`), 주문번호 경계 조건으로 오탐 0건 달성
  - R5 (staged 검사): `tscan staged`로 스테이지 인덱스 내용 검사 및 종료 코드 0/1 연동
  - R6 (pre-commit 훅): 서명 주석 기반 안전한 훅 설치/해제 및 타사 훅 보존
  - R7 (.tscanignore): `path:line`, `kind:path`, 글롭 패턴 필터링 지원
  - R8 (Textual TUI): 비동기 워커 스캔, 목록 탐색, 앞뒤 2줄 문맥 마스킹 미리 보기
  - R9 (과거 이력 검사): `tscan history`로 과거 커밋(`+` 변경분) 역추적
  - R10 (--json 및 종료 코드): 0(정상), 1(발견), 2(오류) 표준 종료 코드 체계 확립
  - R11 (사용자 커스텀 규칙): `.tscan.toml` 및 `~/.tscan/rules.toml` TOML 정규식 규칙 병합
  - R12 (--summary): 종류별, 파일별 건수 및 건너뛴 파일 통계 요약
  - R13 (건너뛰기 필터): 1MB 초과, 바이너리(NUL 바이트), `.git`/`.venv`/`node_modules` 배제
  - R14 (전역 설치): `uv tool install --editable .`로 어느 디렉터리에서나 `tscan` 실행 가능
- **회귀 테스트 결과:** `uv run pytest -q` 실행 결과 **19 passed in 1.66s**
- **Zero Leak 검증:** CLI 출력, JSON, TUI 미리 보기, Git hook 메시지 어디에도 실제/가짜 원본 비밀값이 노출되지 않음을 전수 확인.
