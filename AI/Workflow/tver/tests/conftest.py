import json
from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"


@pytest.fixture
def v1() -> dict:
    return json.loads((DATA / "helpdesk-v1.json").read_text(encoding="utf-8"))


@pytest.fixture
def v2() -> dict:
    return json.loads((DATA / "helpdesk-v2.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch) -> Path:
    """Every test gets its own store and HOME; ~/.tver/store is never touched."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    store = tmp_path / "store"
    monkeypatch.setenv("TVER_REPO", str(store))
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
    return store
