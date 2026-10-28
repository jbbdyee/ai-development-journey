import json
import subprocess
from pathlib import Path

import pytest

from tver import engine
from tver.cli import main
from tver.store import Store, StoreError, resolve_repo, safe_name

from .conftest import DATA

V1, V2, MOVED = (str(DATA / n) for n in ("helpdesk-v1.json", "helpdesk-v2.json", "helpdesk-v1-moved.json"))


def git_count(repo: Path, *paths: str) -> int:
    """Commits as git itself counts them (not via tver)."""
    out = subprocess.run(["git", "-C", str(repo), "rev-list", "--count", "HEAD", "--", *paths],
                         capture_output=True, text=True, check=True).stdout
    return int(out)


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- repo location (R14 contract)
def test_repo_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("TVER_REPO", str(tmp_path / "env"))
    assert resolve_repo(tmp_path / "flag") == (tmp_path / "flag").resolve()
    assert resolve_repo() == (tmp_path / "env").resolve()
    monkeypatch.delenv("TVER_REPO")
    assert resolve_repo() == (tmp_path / "home" / ".tver" / "store").resolve()


@pytest.mark.parametrize("raw, expected", [
    ("helpdesk.json", "helpdesk"),
    ("74 IT helpdesk v2 (provided)", "74-it-helpdesk-v2-provided"),
    ("ops/helpdesk prod", "ops-helpdesk-prod"),
    ("헬프데스크 설정.json", "헬프데스크-설정"),
    ("../../etc", "etc"),
    ("  ", "workflow"),
])
def test_safe_name(raw, expected):
    assert safe_name(raw) == expected


# ---------------------------------------------------------------- R5 save
def test_same_file_twice_makes_one_version(isolated_store):
    store = Store(isolated_store)
    first = store.save(load(V1), "helpdesk")
    again = store.save(load(V1), "helpdesk")
    assert first.saved and first.first
    assert not again.saved and again.rev == first.rev
    assert len(store.versions("helpdesk")) == 1
    assert git_count(isolated_store) == 1


def test_moved_copy_is_not_a_new_version(isolated_store):
    store = Store(isolated_store)
    store.save(load(V1), "helpdesk")
    assert not store.save(load(MOVED), "helpdesk").saved
    assert git_count(isolated_store) == 1


def test_changed_file_is_committed_with_summary(isolated_store):
    store = Store(isolated_store)
    store.save(load(V1), "helpdesk")
    result = store.save(load(V2), "helpdesk")
    assert result.saved and engine.summary(result.changes) == "7 change(s) · model 1 · prompt 1 · flow 5"
    assert git_count(isolated_store, "helpdesk.json") == 2
    body = subprocess.run(["git", "-C", str(isolated_store), "log", "-1", "--format=%B"],
                          capture_output=True, text=True, check=True).stdout
    assert body.startswith("helpdesk: 7 change(s) · model 1 · prompt 1 · flow 5\n")
    assert "+ node Review check [flow]" in body
    assert "~ Answer model parameters.model.value [model]" in body


def test_stored_file_is_cleaned_and_stable(isolated_store):
    store = Store(isolated_store)
    store.save(load(V1), "helpdesk")
    text = (isolated_store / "helpdesk.json").read_text(encoding="utf-8")
    assert text == engine.dumps(engine.clean(load(MOVED)))  # same bytes whatever the export order
    stored = json.loads(text)
    assert all("id" not in n and "position" not in n for n in stored["nodes"])
    assert subprocess.run(["git", "-C", str(isolated_store), "status", "--porcelain"],
                          capture_output=True, text=True).stdout == ""


def test_workflows_are_kept_apart(isolated_store):
    store = Store(isolated_store)
    store.save(load(V1), "helpdesk")
    store.save(load(V2), "helpdesk-copy")
    assert store.names() == ["helpdesk", "helpdesk-copy"]
    assert len(store.versions("helpdesk")) == len(store.versions("helpdesk-copy")) == 1


def test_refuses_folder_that_is_not_a_store(tmp_path):
    folder = tmp_path / "someone-elses-repo"
    folder.mkdir()
    (folder / "keep.txt").write_text("mine")
    with pytest.raises(StoreError, match="not a tver store"):
        Store(folder).save(load(V1), "helpdesk")
    assert sorted(p.name for p in folder.iterdir()) == ["keep.txt"]


# ---------------------------------------------------------------- R6 log and revision diff
def test_read_any_two_revisions(isolated_store):
    store = Store(isolated_store)
    store.save(load(V1), "helpdesk")
    store.save(load(V2), "helpdesk")
    new, old = store.versions("helpdesk")
    assert engine.compare(store.read(old.rev, "helpdesk"), store.read(new.rev, "helpdesk")) == \
        engine.compare(load(V1), load(V2))
    with pytest.raises(StoreError, match="no version at revision"):
        store.read("nope", "helpdesk")
    with pytest.raises(StoreError, match="no saved versions"):
        store.read(new.rev, "other")


def test_cli_save_log_and_revision_diff(isolated_store, capsys):
    assert main(["save", V1, "--name", "helpdesk"]) == 0
    assert "first version · 9 node(s)" in capsys.readouterr().out
    assert main(["save", V2, "-n", "helpdesk"]) == 0
    assert "7 change(s) · model 1 · prompt 1 · flow 5  (2 version(s))" in capsys.readouterr().out
    assert main(["save", V2, "-n", "helpdesk"]) == 0
    assert capsys.readouterr().out.startswith("no change  helpdesk matches")

    assert main(["log", "helpdesk"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("helpdesk · 2 version(s)")
    assert len(lines) == 3
    assert lines[1].endswith("7 change(s) · model 1 · prompt 1 · flow 5")
    assert lines[2].endswith("first version · 9 node(s)")
    new, old = lines[1].split()[0], lines[2].split()[0]

    assert main(["diff", old, new, "helpdesk"]) == 1
    out = capsys.readouterr().out
    file_out = (main(["diff", V1, V2]), capsys.readouterr().out)[1]
    assert out.splitlines()[1:] == file_out.splitlines()[1:]  # same body and summary as R1 · R4
    assert git_count(isolated_store) == 2


def test_cli_repo_flag_beats_env(tmp_path, isolated_store, capsys):
    other = tmp_path / "flag-store"
    assert main(["--repo", str(other), "save", V1]) == 0
    assert main(["save", "--repo", str(other), V2, "-n", "helpdesk-v1"]) == 0
    assert not isolated_store.exists()
    assert git_count(other, "helpdesk-v1.json") == 2
    assert main(["log", "--repo", str(other)]) == 0
    assert "helpdesk-v1  (2 version(s))" in capsys.readouterr().out


def test_cli_errors(isolated_store, capsys):
    assert main(["log", "helpdesk"]) == 2
    assert "no tver store" in capsys.readouterr().err
    main(["save", V1, "-n", "helpdesk"])
    capsys.readouterr()
    assert main(["log", "nothing"]) == 2
    assert "no saved versions of 'nothing'" in capsys.readouterr().err
    assert main(["diff", "HEAD", "nope", "helpdesk"]) == 2
    assert "no version at revision 'nope'" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["diff", "only-one"])
