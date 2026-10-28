"""R7: secret-looking values are refused and never printed. All keys here are fake."""

import copy
import json
import subprocess

from tver import engine, secrets
from tver.cli import main
from tver.store import SecretsFound, Store

from .conftest import DATA

# Built at run time so secret scanners do not flag this test file; the value is fake.
FAKE_KEY = "sk" + "-proj-" + "FAKEfakeFAKEfake1234567890abcdefTEST"
FAKE_BEARER = "Bearer abcdefghijklmnopqrstuvwxyz0123456789FAKE"


def with_key(v1: dict) -> dict:
    wf = copy.deepcopy(v1)
    node = next(n for n in wf["nodes"] if n["name"] == "Search FAQ")
    node["parameters"]["sendHeaders"] = True
    node["parameters"]["headerParameters"] = {"parameters": [{"name": "x-api-key", "value": "plainsecret123"}]}
    model = next(n for n in wf["nodes"] if n["name"] == "Answer model")
    model["parameters"]["options"]["apiKey"] = FAKE_KEY
    get = next(n for n in wf["nodes"] if n["name"] == "Get ticket")
    get["parameters"]["options"]["auth"] = FAKE_BEARER
    return wf


def test_find_secrets_masks_values(v1):
    found = secrets.find_secrets(with_key(v1))
    kinds = {(f.node, f.path, f.kind) for f in found}
    assert ("Answer model", "parameters.options.apiKey", "openai-style key") in kinds
    assert ("Get ticket", "parameters.options.auth", "bearer token") in kinds
    assert ("Search FAQ", "parameters.headerParameters.parameters[0].value", "literal secret field") in kinds
    text = repr(found)
    assert FAKE_KEY not in text and "plainsecret123" not in text and "abcdefghijklmnop" not in text
    assert any(f.masked == f"sk-…({len(FAKE_KEY)} chars)" for f in found)


def test_clean_reference_workflows_have_no_findings(v1, v2):
    # credential references ({id, name}) and expressions like ={{ $env.KEY }} are not secrets
    wf = copy.deepcopy(v1)
    next(n for n in wf["nodes"] if n["name"] == "Get ticket")["parameters"]["options"]["token"] = "={{ $env.TOKEN }}"
    assert secrets.find_secrets(v1) == secrets.find_secrets(v2) == secrets.find_secrets(wf) == []


def test_save_refuses_and_store_does_not_grow(isolated_store, v1):
    store = Store(isolated_store)
    store.save(v1, "helpdesk")
    try:
        store.save(with_key(v1), "helpdesk")
        raise AssertionError("expected refusal")
    except SecretsFound as exc:
        assert FAKE_KEY not in str(exc) and "plainsecret123" not in str(exc)
    assert len(store.versions("helpdesk")) == 1
    log = subprocess.run(["git", "-C", str(isolated_store), "log", "-p", "--all"], capture_output=True, text=True).stdout
    assert FAKE_KEY not in log and "plainsecret123" not in log


def test_first_save_with_secret_creates_nothing(isolated_store, v1):
    try:
        Store(isolated_store).save(with_key(v1), "helpdesk")
    except SecretsFound:
        pass
    assert not isolated_store.exists()


def test_cli_save_refusal_hides_value(isolated_store, tmp_path, capsys, v1):
    path = tmp_path / "leaky.json"
    path.write_text(json.dumps(with_key(v1)), encoding="utf-8")
    assert main(["save", str(path)]) == 2
    out = capsys.readouterr()
    assert "refused" in out.err and "sk-…(" in out.err
    for text in (out.out, out.err):
        assert FAKE_KEY not in text and "plainsecret123" not in text
    assert main(["--json", "save", str(path)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert "refused" in payload["error"] and FAKE_KEY not in json.dumps(payload)


def test_diff_output_masks_secrets(tmp_path, capsys, v1):
    path = tmp_path / "leaky.json"
    path.write_text(json.dumps(with_key(v1)), encoding="utf-8")
    assert main(["diff", str(DATA / "helpdesk-v1.json"), str(path)]) == 1
    text = capsys.readouterr().out
    assert main(["--json", "diff", str(DATA / "helpdesk-v1.json"), str(path)]) == 1
    text += capsys.readouterr().out
    assert "parameters.options.apiKey" in text
    assert FAKE_KEY not in text and "plainsecret123" not in text and "abcdefghijklmnopqrstuvwxyz" not in text


def test_long_text_with_key_is_masked_in_line_diff(v1):
    wf = copy.deepcopy(v1)
    answer = next(n for n in wf["nodes"] if n["name"] == "Answer")
    answer["parameters"]["options"]["systemMessage"] += f"\nUse key {FAKE_KEY} for lookups."
    change = next(c for c in engine.compare(v1, wf) if c.category == "prompt")
    assert any("sk-…(" in line for line in change.lines)
    assert FAKE_KEY not in json.dumps(change.__dict__)
