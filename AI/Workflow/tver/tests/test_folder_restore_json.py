"""R13 folder save, R10 restore, R11 JSON output and exit codes."""

import json
import shutil
import subprocess

from tver import engine
from tver.cli import main
from tver.store import Store

from .conftest import DATA

V1, V2 = str(DATA / "helpdesk-v1.json"), str(DATA / "helpdesk-v2.json")


def mixed_folder(tmp_path):
    folder = tmp_path / "my-work"
    folder.mkdir()
    shutil.copy(DATA / "helpdesk-v1.json", folder / "helpdesk.json")
    shutil.copy(DATA / "helpdesk-v2.json", folder / "Helpdesk Next.json")
    (folder / "cases.json").write_text('{"cases": [{"q": "VPN?", "expect": "FAQ-003"}]}', encoding="utf-8")
    (folder / "list.json").write_text("[1, 2]", encoding="utf-8")
    (folder / "broken.json").write_text("{oops", encoding="utf-8")
    (folder / "notes.md").write_text("# memo", encoding="utf-8")
    (folder / ".DS_Store").write_bytes(b"\0")
    (folder / "sub").mkdir()
    shutil.copy(DATA / "helpdesk-v1.json", folder / "sub" / "deep.json")
    return folder


# ---------------------------------------------------------------- R13
def test_folder_saves_only_workflows(isolated_store, tmp_path, capsys):
    folder = mixed_folder(tmp_path)
    assert main(["save", str(folder)]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == "2 saved · 0 unchanged · 4 skipped · 0 refused · 0 error"
    assert Store(isolated_store).names() == ["helpdesk", "helpdesk-next"]
    for skipped in ("cases.json", "list.json", "broken.json", "notes.md"):
        assert f"skipped   {skipped}" in out

    assert main(["--json", "save", str(folder)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"] == {"saved": 0, "unchanged": 2, "skipped": 4, "refused": 0, "error": 0}


def test_folder_with_secret_reports_refused(isolated_store, tmp_path, capsys):
    folder = mixed_folder(tmp_path)
    leaky = json.loads((DATA / "helpdesk-v1.json").read_text())
    leaky["nodes"][0]["parameters"]["apiKey"] = "sk" + "-FAKEfakeFAKEfake0123456789"  # fake, split for scanners
    (folder / "leaky.json").write_text(json.dumps(leaky), encoding="utf-8")
    assert main(["save", str(folder)]) == 2
    out = capsys.readouterr().out
    assert "refused   leaky.json" in out and "sk-FAKEfakeFAKE" not in out
    assert "leaky" not in Store(isolated_store).names()


def test_folder_name_collision_is_error(isolated_store, tmp_path, capsys):
    folder = tmp_path / "f"
    folder.mkdir()
    shutil.copy(DATA / "helpdesk-v1.json", folder / "Help Desk.json")
    shutil.copy(DATA / "helpdesk-v2.json", folder / "help-desk.json")
    assert main(["save", str(folder)]) == 2
    assert "already used by Help Desk.json" in capsys.readouterr().out
    assert len(Store(isolated_store).versions("help-desk")) == 1


# ---------------------------------------------------------------- R10
def test_restore_writes_file_and_keeps_store(isolated_store, tmp_path, capsys):
    store = Store(isolated_store)
    main(["save", V1, "-n", "helpdesk"])
    main(["save", V2, "-n", "helpdesk"])
    capsys.readouterr()
    old = store.versions("helpdesk")[1].rev
    head = subprocess.run(["git", "-C", str(isolated_store), "rev-parse", "HEAD"], capture_output=True, text=True).stdout

    out = tmp_path / "restored" / "helpdesk-v1.json"
    assert main(["restore", old, "helpdesk", "-o", str(out)]) == 0
    assert "store unchanged" in capsys.readouterr().out
    restored = json.loads(out.read_text(encoding="utf-8"))
    assert engine.compare(restored, json.loads((DATA / "helpdesk-v1.json").read_text())) == []
    assert main(["diff", str(out), V1]) == 0
    assert all(isinstance(n.get("position"), list) for n in restored["nodes"])  # importable layout
    assert len(store.versions("helpdesk")) == 2
    assert subprocess.run(["git", "-C", str(isolated_store), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout == head
    assert subprocess.run(["git", "-C", str(isolated_store), "status", "--porcelain"],
                          capture_output=True, text=True).stdout == ""

    # existing file is protected unless --force
    capsys.readouterr()
    assert main(["restore", old, "helpdesk", "-o", str(out)]) == 2
    assert "already exists" in capsys.readouterr().err
    assert main(["restore", "HEAD", "helpdesk", "-o", str(out), "--force"]) == 0
    assert main(["diff", str(out), V2]) == 0
    capsys.readouterr()
    assert main(["restore", old, "helpdesk", "-o", "-"]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "74 IT helpdesk v1 (provided)"
    assert main(["restore", "nope", "helpdesk", "-o", str(tmp_path / "x.json")]) == 2
    assert not (tmp_path / "x.json").exists()


# ---------------------------------------------------------------- R11
def test_diff_exit_codes(tmp_path, capsys):
    assert main(["diff", V1, V1]) == 0
    assert main(["diff", V1, V2]) == 1
    assert main(["diff", V1, str(tmp_path / "missing.json")]) == 2


def test_diff_json_is_parseable(capsys):
    assert main(["--json", "diff", V1, V2]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] is True and payload["total"] == 7
    assert payload["counts"] == {"model": 1, "prompt": 1, "flow": 5}
    assert payload["summary"] == "7 change(s) · model 1 · prompt 1 · flow 5"
    prompt = next(c for c in payload["changes"] if c["category"] == "prompt")
    assert any("[FAQ-003]" in line for line in prompt["lines"])
    assert main(["diff", V1, V1, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["changed"] is False


def test_json_errors_and_other_commands(tmp_path, capsys):
    assert main(["--json", "diff", V1, str(tmp_path / "missing.json")]) == 2
    assert "file not found" in json.loads(capsys.readouterr().out)["error"]
    assert main(["--json", "log", "helpdesk"]) == 2
    assert "error" in json.loads(capsys.readouterr().out)
    assert main(["save", V1, "--json", "-n", "helpdesk"]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["status"] == "saved" and saved["versions"] == 1
    assert main(["save", V1, "--json", "-n", "helpdesk"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "unchanged"
    assert main(["log", "helpdesk", "--json"]) == 0
    versions = json.loads(capsys.readouterr().out)["versions"]
    assert len(versions) == 1 and versions[0]["summary"] == "first version · 9 node(s)"
    assert main(["--json", "log"]) == 0
    assert json.loads(capsys.readouterr().out)["workflows"] == [{"name": "helpdesk", "versions": 1}]
    assert main(["save", str(tmp_path / "missing.json")]) == 2
