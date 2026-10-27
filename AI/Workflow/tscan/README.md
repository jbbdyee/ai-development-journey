# tscan

**Git 저장소와 로컬 디렉터리에서 노출된 API 키, `.env` 값, 개인정보를 안전하게 가린(마스킹된) 채로 탐지하고 커밋 전에 차단하는 터미널(CLI 및 Textual TUI) 보안 도구입니다.**

---

## 1. 만든 이유

개발 환경이나 배포 전 저장소에서 OpenAI API 키, 개인 연락처, 주민등록번호 등이 실수로 커밋되어 유출되는 사고가 빈번히 발생합니다.
비밀이 한 번 Git 커밋에 포함되면 파일을 삭제하더라도 커밋 히스토리에 영구적으로 남아 전체 키 폐기 및 재발급이라는 막대한 운영 비용을 초래합니다.

`tscan`은 다음 핵심 가치를 바탕으로 설계되었습니다:
- **Zero-Retention (원천 유출 차단):** 탐지 즉시 마스킹 처리하여 메모리 객체, 로그, 파일 출력, CLI/JSON 어디에도 원본 비밀값을 남기지 않습니다.
- **Git Staged 중심 사전 차단:** `git commit` 직전 스테이징된 내용(`git show :<path>`)만 빠르게 검사하여 커밋을 안전하게 중단합니다.
- **오탐(False Positive) 최소화:** 단순 날짜(`2026-10-27`), 버전(`1.0.10`), 주문번호 등을 전화번호나 주민번호로 오인하지 않도록 경계 조건을 정밀화했습니다.
- **인터랙티브 TUI & 안전한 문맥 미리 보기:** Textual 기반 UI에서 탐지 목록을 확인하고, 앞뒤 2줄 미리 보기에서도 다른 비밀까지 함께 가려진 안전한 문맥을 확인하며 단축키 하나로 예외 처리를 할 수 있습니다.

---

## 2. 주요 기능

- **다양한 민감 정보 탐지 (R1):** OpenAI API 키(`sk-…`), 한국 휴대전화 번호, 이메일 주소, 주민등록번호(RRN) 탐지
- **완전 마스킹 (R2):** `sk-…****…xx`, `010-****-xxxx`, `u***@domain`, `xxxxxx-*******` 등 안전한 마스킹 제공
- **`.env` 값 추적 (R3):** 프로젝트 내 `.env` 파일에 선언된 6자 이상의 설정값이 타 소스코드 파일에 그대로 복사되어 있는지 탐지 (`env_value`)
- **정밀한 오탐 방지 (R4):** 날짜, 시맨틱 버전, 12자리 주문번호 오탐 0건 보장
- **Git Staged 검사 (R5):** `git add`된 내용만 즉시 검사하여 비밀 발견 시 종료 코드 `1`, 없으면 `0` 반환
- **Pre-commit 훅 관리 (R6):** `# Managed by tscan` 서명을 통해 타사 훅(Husky 등)을 파괴하지 않고 안전하게 등록(`install-hook`) 및 해제(`uninstall-hook`)
- **예외 무시 목록 (R7):** `.tscanignore` 파일 지원 (`path:line`, `kind:path`, 글롭 패턴 경로)
- **대화형 TUI 및 문맥 미리 보기 (R8):** 비동기 백그라운드 워커 스캔, 목록 탐색, 앞뒤 2줄 문맥 마스킹 미리 보기
- **과거 커밋 히스토리 추적 (R9):** `tscan history` 명령으로 `git log -p`를 역추적하여 과거에 커밋된 비밀 탐지
- **CI/CD 파이프라인 연계 (R10):** `--json` 기계 판독 포맷 및 표준 종료 코드 (0: 정상, 1: 비밀 발견, 2: 오류) 지원
- **커스텀 탐지 규칙 확장 (R11):** `.tscan.toml`(프로젝트) 및 `~/.tscan/rules.toml`(전역) TOML 설정으로 사내 사번/토큰 정규식 추가
- **요약 보고서 (R12):** `--summary`로 검사/건너뛴 파일 수 및 종류별/파일별 통계 출력
- **스마트 건너뛰기 필터 (R13):** `.git`, `node_modules`, `.venv`, 1MB 초과 파일, NUL 바이트 바이너리 파일 자동 제외
- **어디서나 실행 (R14):** `uv tool install --editable .`로 전역 CLI 명령어 등록

---

## 3. 설치

Python 3.11 이상 및 [uv](https://docs.astral.sh/uv/)가 필요합니다.

```bash
cd AI/Workflow/tscan
uv tool install --editable .

# 설치 확인
which tscan
tscan --help
```

---

## 4. 사용법

### 4.1. 대화형 TUI 모드
터미널에서 디렉터리 경로를 지정하면 대화형 TUI가 실행됩니다.

```bash
tscan .
tscan /path/to/project
```
- `↑` / `↓` : 탐지 목록 탐색 및 하단 마스킹 미리 보기 확인
- `[i]` : 선택한 항목을 `.tscanignore`에 즉시 추가하고 자동 재스캔
- `[r]` : 수동 다시 검사
- `[q]` : TUI 종료

### 4.2. CLI 텍스트 및 JSON 검사
```bash
# 기본 일반 텍스트 출력
tscan scan . --plain

# 통계 요약 포함 출력
tscan scan . --plain --summary

# CI/CD 자동화용 JSON 출력
tscan scan . --json
echo "Exit Code: $?" # 0: 정상, 1: 탐지됨, 2: 실행오류
```

### 4.3. Git 스테이징 검사 및 Pre-commit 훅
```bash
# 커밋 직전 스테이징된 내용만 검사
tscan staged
echo $? # 1이면 커밋 중단 필요

# Pre-commit 훅 설치 (커밋 시 저절로 tscan staged 실행)
tscan install-hook

# Pre-commit 훅 제거
tscan uninstall-hook
```

### 4.4. 과거 Git 커밋 이력 검사
```bash
# 과거 커밋에서 유입되었던 비밀 역추적
tscan history

# JSON 출력
tscan history --json
```

### 4.5. 사내 맞춤 탐지 규칙 (.tscan.toml)
프로젝트 루트에 `.tscan.toml`을 두거나 `~/.tscan/rules.toml`에 규칙을 정의합니다:

```toml
[[rules]]
name = "emp_id"
pattern = '(?<![0-9a-zA-Z])E-\d{6}(?![0-9a-zA-Z])'
```

---

## 5. 기술 설계

- `scanner.py`와 `patterns.py`가 파일 내용과 탐지 규칙을 처리하고, `masker.py`가 탐지값과 미리 보기 문맥을 가립니다. `Finding`에는 원문 비밀값 필드가 없습니다.
- `git.py`는 작업 파일 대신 Git 인덱스의 스테이징된 바이트를 읽습니다. `hooks.py`는 기존 타사 pre-commit 훅을 발견하면 설치를 중단합니다.
- `app.py`는 Textual 워커에서 폴더 검사를 실행합니다. JSON·일반 출력과 커밋 훅은 TUI 없이 CLI와 검사 엔진을 사용합니다.
- `.tscanignore`와 TOML 규칙은 프로젝트별 예외와 사용자 정의 패턴을 제공합니다. 실제 비밀을 발견했다면 해당 키를 폐기하고 재발급해야 합니다.

## 6. 테스트 결과

모든 테스트는 런타임에 동적으로 조립된 가짜 비밀 문자열로 수행되어 저장소 자체를 오염시키지 않습니다.

```bash
$ uv run pytest -q
...................                                                      [100%]
19 passed in 2.14s
```

- `test_engine.py` (5건): 비밀 탐지, 마스킹, 오탐 방지(날짜/버전/주문번호), .env 값 탐지, 건너뛰기 필터
- `test_git_hook.py` (5건): staged 검사, git index 격리, 훅 설치/해제, 커밋 차단, 기존 훅 보호
- `test_tui.py` (3건): TUI 마운트, 미리 보기 앞뒤 줄 마스킹, 빈 디렉터리, `[i]` 무시 등록 및 재검사
- `test_ignore_json.py` (4건): `.tscanignore` 규칙 파싱 및 필터링, `--json` 및 종료 코드, `--summary`
- `test_history_config.py` (2건): `.tscan.toml` 커스텀 규칙, `tscan history` 과거 커밋 탐지

---

## 7. 알려진 한계 및 향후 과제

1. **클라우드 API 자동 폐기 연동 부재:** 발견된 API 키에 대해 OpenAI나 AWS 등의 클라우드 공급업체 API를 호출하여 즉시 폐기/재발급하는 기능은 지원하지 않습니다. (보안 담당자 수동 처리 필요)
2. **Git History 재작성(Rewrite) 미지원:** `tscan history`로 과거 커밋의 비밀을 찾아내지만, `git filter-repo`나 BFG처럼 과거 커밋을 직접 재작성하여 영구 삭제하는 기능은 포함하지 않습니다.
3. **외부 보안 서버 중앙 집계:** 탐지된 결과를 사내 SIEM이나 중앙 보안 관제 서버로 실시간 전송하는 기능은 제외되어 있으며, 로컬 및 CI 파이프라인에서 종료 코드와 JSON으로 연계하여 활용해야 합니다.
