"""tflow command line entry point."""

import argparse
from pathlib import Path
import sys

from .render import render_markdown, render_tree
from .workflow import load_workflow


def main() -> int:
    parser = argparse.ArgumentParser(description="n8n 워크플로우 구조 보기")
    parser.add_argument("file", type=Path, help="n8n 워크플로우 JSON 파일")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("-b", "--box", action="store_true", help="박스형 FLOW 보기 (기본값)")
    mode.add_argument("--tree", action="store_true", help="TREE 보기")
    parser.add_argument("--md", action="store_true", help="Mermaid 마크다운 저장")
    parser.add_argument("--text", action="store_true", help="글자 트리 출력")
    args = parser.parse_args()
    try:
        workflow = load_workflow(args.file)
        if args.md:
            output = args.file.with_suffix(".md")
            output.write_text(render_markdown(workflow), encoding="utf-8")
            print(output)
        elif args.text or not (sys.stdin.isatty() and sys.stdout.isatty()):
            print(render_tree(workflow))
        else:
            from .tui import TflowApp
            TflowApp(workflow, args.file, initial_mode="TREE" if args.tree else "FLOW").run()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"tflow: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
