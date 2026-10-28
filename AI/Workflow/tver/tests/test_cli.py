from tver.cli import main

from .conftest import DATA

V1, V2, MOVED = (str(DATA / n) for n in ("helpdesk-v1.json", "helpdesk-v2.json", "helpdesk-v1-moved.json"))


def test_diff_v1_v2_output(capsys):
    assert main(["diff", V1, V2]) == 1  # different (R11)
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[-1] == "7 change(s) · model 1 · prompt 1 · flow 5"
    assert any(l.strip().startswith("+ ") and "[FAQ-003]" in l for l in lines)
    assert '~ Answer model  parameters.model.value: "gpt-4.1-mini" → "gpt-5.4-nano"  [model]' in lines
    assert "+ node  Review check (code)  [flow]" in lines
    assert "- link  Answer → Build result (main)  [flow]" in lines
    assert "+ link  Answer → Review check (main)  [flow]" in lines
    assert "+ link  Review check → Build result (main)  [flow]" in lines
    assert "\x1b[" not in out  # no colour codes when not a terminal


def test_diff_moved_copy_is_zero(capsys):
    assert main(["diff", V1, MOVED]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "0 change(s) · model 0 · prompt 0 · flow 0"


def test_diff_error_message(tmp_path, capsys):
    assert main(["diff", V1, str(tmp_path / "nope.json")]) == 2
    err = capsys.readouterr().err
    assert "error:" in err and "file not found" in err


def test_no_command_prints_help(capsys):
    assert main([]) == 2
    assert "diff" in capsys.readouterr().out
