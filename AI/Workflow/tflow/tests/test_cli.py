"""CLI mode and output checks without starting an interactive terminal."""

from io import StringIO
from pathlib import Path
import sys

from tflow import cli
from tflow.tui import TflowApp


SOURCE = Path(__file__).parent / "fixtures/assistant.json"


class TerminalOutput(StringIO):
    def isatty(self):
        return True


def test_cli_box_tree_and_markdown(monkeypatch, tmp_path):
    source = tmp_path / "assistant.json"
    source.write_bytes(SOURCE.read_bytes())
    started = []
    monkeypatch.setattr(TflowApp, "run", lambda self: started.append(self._mode))
    monkeypatch.setattr(sys, "stdin", TerminalOutput())
    monkeypatch.setattr(sys, "stdout", TerminalOutput())
    for flags, expected in (([], "FLOW"), (["-b"], "FLOW"),
                            (["--box"], "FLOW"), (["--tree"], "TREE")):
        monkeypatch.setattr(sys, "argv", ["tflow", *flags, str(source)])
        assert cli.main() == 0
        assert started[-1] == expected
    monkeypatch.setattr(sys, "argv", ["tflow", str(source), "--md"])
    assert cli.main() == 0
    assert "```mermaid" in source.with_suffix(".md").read_text()
