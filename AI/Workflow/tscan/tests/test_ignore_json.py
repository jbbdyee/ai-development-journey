import json
from pathlib import Path
import pytest
from tscan.cli import main
from tscan.ignore import IgnoreFilter, IgnoreRule
from tscan.models import Finding
from tscan.scanner import scan_folder


def test_ignore_rules_matching():
    # 1. path:line rule
    rule_pl = IgnoreRule(rule_type="path_line", pattern="dummy.txt", line=12)
    filt = IgnoreFilter([rule_pl])

    f1 = Finding(kind="phone", path="dummy.txt", line=12, masked="010-****-1234")
    f2 = Finding(kind="phone", path="dummy.txt", line=13, masked="010-****-1234")
    f3 = Finding(kind="phone", path="other.txt", line=12, masked="010-****-1234")

    assert filt.is_ignored(f1) is True
    assert filt.is_ignored(f2) is False
    assert filt.is_ignored(f3) is False

    # 2. kind:path rule
    rule_kp = IgnoreRule(rule_type="kind_path", pattern="docs/*.md", kind="phone")
    filt_kp = IgnoreFilter([rule_kp])

    f4 = Finding(kind="phone", path="docs/readme.md", line=5, masked="010-****-1234")
    f5 = Finding(kind="openai_key", path="docs/readme.md", line=5, masked="sk-…****…yz")
    f6 = Finding(kind="phone", path="src/main.py", line=5, masked="010-****-1234")

    assert filt_kp.is_ignored(f4) is True
    assert filt_kp.is_ignored(f5) is False
    assert filt_kp.is_ignored(f6) is False

    # 3. glob rule
    rule_glob = IgnoreRule(rule_type="glob", pattern="tests/fixtures/*")
    filt_glob = IgnoreFilter([rule_glob])

    f7 = Finding(kind="openai_key", path="tests/fixtures/data.json", line=1, masked="sk-…****…yz")
    f8 = Finding(kind="openai_key", path="src/config.py", line=1, masked="sk-…****…yz")

    assert filt_glob.is_ignored(f7) is True
    assert filt_glob.is_ignored(f8) is False


def test_tscanignore_file_integration(tmp_path: Path):
    # R7: .tscanignore should filter out ignored items
    fake_key = "sk-" + "test-" + "abcdefghijklmnopqrstuvwxyz12"
    fake_phone = "010-" + "5555-" + "4444"

    a_file = tmp_path / "a.txt"
    a_file.write_text(f"key = '{fake_key}'\nphone = '{fake_phone}'\n", encoding="utf-8")

    # Create .tscanignore ignoring line 2 of a.txt
    ignore_file = tmp_path / ".tscanignore"
    ignore_file.write_text("a.txt:2\n", encoding="utf-8")

    summary = scan_folder(tmp_path)
    assert len(summary.findings) == 1
    assert summary.findings[0].kind == "openai_key"


def test_cli_json_and_exit_codes(tmp_path: Path, capsys):
    # R10: --json flag and exit codes (0, 1, 2)
    fake_key = "sk-" + "test-" + "abcdefghijklmnopqrstuvwxyz12"

    target_file = tmp_path / "test.txt"
    target_file.write_text(f"key = '{fake_key}'\n", encoding="utf-8")

    # 1. Exit code 1 when findings found
    exit_code_1 = main(["scan", str(tmp_path), "--json"])
    assert exit_code_1 == 1
    out_1 = capsys.readouterr().out
    data_1 = json.loads(out_1)
    assert data_1["total_findings"] == 1
    assert data_1["findings"][0]["kind"] == "openai_key"
    assert fake_key not in out_1

    # 2. Exit code 0 when clean
    target_file.write_text("clean = true\n", encoding="utf-8")
    exit_code_0 = main(["scan", str(tmp_path), "--json"])
    assert exit_code_0 == 0
    out_0 = capsys.readouterr().out
    data_0 = json.loads(out_0)
    assert data_0["total_findings"] == 0

    # 3. Exit code 2 on error (nonexistent target)
    exit_code_2 = main(["scan", "/nonexistent/path/xyz", "--json"])
    assert exit_code_2 == 2


def test_cli_summary_output(tmp_path: Path, capsys):
    # R12: --summary flag
    fake_phone = "010-" + "1111-" + "2222"
    f = tmp_path / "contact.txt"
    f.write_text(f"phone={fake_phone}\n", encoding="utf-8")

    exit_code = main(["scan", str(tmp_path), "--summary", "--plain"])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "검사 요약 (Summary):" in out
    assert "phone: 1" in out
