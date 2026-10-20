# tflow

n8n 워크플로우 JSON의 노드, 분기, 재합류, 순환을 터미널에서 살펴보는 Python 도구입니다. 트리와 2차원 FLOW 화면, 노드 상세 정보, Mermaid 문서 출력을 제공합니다.

## 실행

Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다.

```bash
cd AI/Workflow/tflow
uv sync --group dev
uv run tflow tests/fixtures/assistant.json
uv run tflow tests/fixtures/it-agent.json --tree
uv run tflow tests/fixtures/it-agent.json --md
uv run pytest -q
```

터미널 화면에서는 `1`로 TREE, `2`로 FLOW를 전환합니다. 방향키로 이동하고 Enter로 상세 정보를 엽니다. `e`는 Agent 지시문 언어, `v`는 긴 지시문, `w`는 경고를 전환합니다. `m`은 Mermaid 파일을 저장하고 `q`는 종료합니다. 비대화형 출력에는 텍스트 트리가 표시되며 `--text`로 명시할 수 있습니다.

한국어 노드 설명과 영어 Agent 지시문 번역은 `OPENAI_API_KEY` 환경변수가 있을 때 동작합니다. 키가 없어도 탐색과 Mermaid 출력은 사용할 수 있습니다. 설명과 번역 캐시는 현재 실행 폴더의 `.tflow-cache/`에 저장되며, `TFLOW_CACHE_DIR`로 위치를 바꿀 수 있습니다. 워크플로우의 Credential 객체와 비밀값은 LLM 요청에서 제외하도록 처리합니다.

`tests/fixtures/`에는 자격 증명 참조를 제거한 테스트용 워크플로우가 있습니다. 실제 워크플로우와 API 키는 저장소에 추가하지 마세요.
