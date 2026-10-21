"""Plain text CLI with review and per-run records."""

import argparse
from pathlib import Path

from tcrew.core import LLM, execute, load_config
from tcrew.openai_client import OpenAILLM
from tcrew.records import redact, save_record


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "crew.yaml"
DEFAULT_RUNS = Path.cwd() / "runs"


def main(argv: list[str] | None = None, *, llm: LLM | None = None, runs_dir: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tcrew")
    parser.add_argument("question")
    parser.add_argument("--plain", action="store_true", help="역할별 답을 글자로 출력")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    if not args.plain:
        try:
            config = load_config(args.config)
        except ValueError as exc:
            parser.exit(1, f"tcrew: {exc}\n")
        from tcrew.tui import CrewApp
        CrewApp(args.question, config, llm or OpenAILLM(), runs_dir or DEFAULT_RUNS).run()
        return 0
    try:
        result = execute(args.question, load_config(args.config), llm or OpenAILLM())
        save_record(result, runs_dir or DEFAULT_RUNS)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"tcrew: {exc}\n")
    for item in result.results:
        label = f"{item.name}#{item.attempt}" if item.attempt > 1 else item.name
        print(f"=== {label} ===")
        print(redact(item.output))
    if result.status != "passed":
        print(f"실패: {result.reason}")
        return 1
    return 0
