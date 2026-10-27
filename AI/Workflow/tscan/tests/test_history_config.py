from pathlib import Path
import subprocess
import pytest
from tscan.cli import main
from tscan.config import load_custom_rules
from tscan.history import scan_history
from tscan.scanner import scan_folder


def init_git_repo(path: Path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)


def test_custom_rules_from_tscan_toml(tmp_path: Path):
    # R11: .tscan.toml custom rules
    config_file = tmp_path / ".tscan.toml"
    config_file.write_text(
        "[[rules]]\nname = 'emp_id'\npattern = '(?<![0-9a-zA-Z])E-\\d{6}(?![0-9a-zA-Z])'\n",
        encoding="utf-8",
    )

    data_file = tmp_path / "employee.txt"
    data_file.write_text("Lead engineer: E-123456\nOther: normal text\n", encoding="utf-8")

    summary = scan_folder(tmp_path)
    kinds = [f.kind for f in summary.findings]

    assert "emp_id" in kinds
    emp_finding = next(f for f in summary.findings if f.kind == "emp_id")
    assert "E-" in emp_finding.masked
    assert "123456" not in emp_finding.masked


def test_git_history_scan(tmp_path: Path, monkeypatch):
    # R9: tscan history detects secrets committed in the past even after deletion
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    # Commit 1: Clean
    doc = tmp_path / "notes.txt"
    doc.write_text("First clean version\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Commit 1: clean"], cwd=tmp_path, check=True)

    # Commit 2: Leaked secret
    fake_key = "sk-" + "test-" + "abcdefghijklmnopqrstuv12"
    doc.write_text(f"First clean version\napi_key = '{fake_key}'\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Commit 2: leaked key"], cwd=tmp_path, check=True)

    # Commit 3: Remove secret
    doc.write_text("First clean version\napi_key = removed\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "Commit 3: removed key"], cwd=tmp_path, check=True)

    # Working tree is clean now:
    summary_now = scan_folder(tmp_path)
    assert len(summary_now.findings) == 0

    # History scan should find the secret in Commit 2
    history_findings = scan_history(tmp_path)
    assert len(history_findings) >= 1
    assert history_findings[0].kind == "openai_key"
    assert history_findings[0].path == "notes.txt"
    assert fake_key not in history_findings[0].masked
    assert "sk-…****…" in history_findings[0].masked

    # Test CLI history command
    exit_code = main(["history"])
    assert exit_code == 1
