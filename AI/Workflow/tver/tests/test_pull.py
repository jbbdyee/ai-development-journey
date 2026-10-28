"""R9: pull reads n8n through a fake `docker` and never sends anything but the export."""

import copy
import json
import os
import stat
import sys

from tver.cli import main
from tver.n8n import EXPORT, parse_export, store_names
from tver.store import Store

from .conftest import DATA


def exported(v1, v2):
    a, b, c = copy.deepcopy(v1), copy.deepcopy(v2), copy.deepcopy(v1)
    a.update(id="wfA0001", name="Helpdesk", isArchived=False, active=True, versionId="x1")
    b.update(id="wfB0002", name="Helpdesk", isArchived=False, active=False)  # same name, other workflow
    c.update(id="wfC0003", name="옛 실험 / old", isArchived=True)
    d = copy.deepcopy(v1)
    d.update(id="wfD0004", name="헬프데스크 실험/v2", isArchived=False)
    return [a, b, c, d]


def fake_docker(tmp_path, monkeypatch, payload, log_lines="") -> tuple:
    """A `docker` on PATH that prints `payload` for the export and records every call."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "docker-calls.jsonl"
    data = tmp_path / "export.json"
    data.write_text(log_lines + json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    script = bin_dir / "docker"
    script.write_text(f"""#!{sys.executable}
import json, sys
open({str(calls)!r}, "a").write(json.dumps(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[:1] == ["ps"]:
    print("course-n8n")
elif args[:1] == ["exec"] and args[2:] == {list(EXPORT)!r}:
    sys.stdout.write(open({str(data)!r}, encoding="utf-8").read())
else:
    sys.stderr.write("unexpected docker call")
    sys.exit(9)
""", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("TVER_N8N_CONTAINER", raising=False)
    return calls, data


def read_calls(calls):
    return [json.loads(line) for line in calls.read_text().splitlines()]


def test_pull_saves_each_workflow_read_only(isolated_store, tmp_path, monkeypatch, capsys, v1, v2):
    calls, data = fake_docker(tmp_path, monkeypatch, exported(v1, v2), log_lines="Permissions 0644 warning\n")
    before = data.read_bytes()
    assert main(["pull"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == "3 new version(s)"
    assert "skipped   옛 실험 / old" in out
    assert Store(isolated_store).names() == ["helpdesk-wfa0001", "helpdesk-wfb0002", "헬프데스크-실험-v2"]
    # only the container lookup and the read-only export were sent
    assert read_calls(calls) == [
        ["ps", "--filter", "label=com.docker.compose.service=n8n", "--format", "{{.Names}}"],
        ["exec", "course-n8n", *EXPORT],
    ]
    assert data.read_bytes() == before

    # second pull: nothing changed, nothing committed
    assert main(["pull", "--container", "course-n8n"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "0 new version(s)"
    assert read_calls(calls)[-1] == ["exec", "course-n8n", *EXPORT]
    assert sum(len(Store(isolated_store).versions(n)) for n in Store(isolated_store).names()) == 3


def test_pull_from_file_and_json(isolated_store, tmp_path, capsys, v1, v2):
    export = tmp_path / "all.json"
    export.write_text(json.dumps(exported(v1, v2)), encoding="utf-8")
    assert main(["--json", "pull", "--file", str(export), "--include-archived"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["new_versions"] == 4 and payload["counts"]["saved"] == 4


def test_pull_refuses_workflow_with_secret(isolated_store, tmp_path, capsys, v1, v2):
    flows = exported(v1, v2)
    flows[0]["nodes"][0]["parameters"]["apiKey"] = "sk" + "-FAKEfakeFAKEfake0123456789"  # fake, split for scanners
    export = tmp_path / "all.json"
    export.write_text(json.dumps(flows), encoding="utf-8")
    assert main(["pull", "--file", str(export)]) == 2
    out = capsys.readouterr().out
    assert "refused   Helpdesk" in out and "sk-FAKEfakeFAKE" not in out
    assert "helpdesk-wfa0001" not in Store(isolated_store).names()


def test_pull_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))  # no docker at all
    assert main(["pull"]) == 2
    assert "docker" in capsys.readouterr().err
    assert main(["pull", "--file", str(tmp_path / "none.json")]) == 2


def test_parse_and_names():
    assert parse_export("", "x") == []
    assert parse_export('warn [x]\n[{"name": "a"}]', "x") == [{"name": "a"}]
    flows = [{"name": "A b", "id": "1"}, {"name": "a-b", "id": "2"}, {"name": "c"}, {"name": "c"}]
    assert store_names(flows) == ["a-b-1", "a-b-2", "c-1", "c-2"]
    same = [{"name": "x", "id": "7"}, {"name": "x", "id": "7"}]
    assert store_names(same) == ["x-7", "x-7-2"]
