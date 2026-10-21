"""Local JSON chooser shown when tflow is started without a file path."""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DirectoryTree, Input, Static


class JsonTree(DirectoryTree):
    def filter_paths(self, paths):
        return [path for path in paths if path.is_dir() or path.suffix.lower() == ".json"]


class FilePicker(App[Path | None]):
    CSS = """
    Screen { background: #0c1422; color: #d9e5f3; }
    #picker { width: 100%; height: 1fr; padding: 1 2; }
    #picker-title { height: 2; color: #86c5ff; text-style: bold; }
    #path-input { height: 3; }
    #json-tree { height: 1fr; border: round #295377; background: #111e31; }
    #picker-help { height: 2; color: #b7c9df; }
    """
    BINDINGS = [("q", "quit_picker", "취소"), ("escape", "quit_picker", "취소"),
                ("tab", "focus_next", "포커스 이동")]

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Static("TFLOW | JSON 워크플로우 선택", id="picker-title")
            yield Input(placeholder="JSON 파일 경로를 입력하거나 아래 목록에서 선택", id="path-input")
            yield JsonTree(Path.home(), id="json-tree")
            yield Static("Enter 파일 선택  ·  Tab 입력/목록 이동  ·  Esc 취소", id="picker-help")

    def on_mount(self) -> None:
        self.query_one("#path-input", Input).focus()

    def _choose(self, path: Path) -> None:
        path = path.expanduser().resolve()
        if path.suffix.lower() != ".json" or not path.is_file():
            self.notify("존재하는 JSON 파일을 선택하세요.", severity="error")
            return
        self.exit(path)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._choose(Path(event.value))

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self._choose(event.path)

    def action_quit_picker(self) -> None:
        self.exit(None)
