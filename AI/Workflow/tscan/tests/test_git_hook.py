import os
from pathlib import Path
import stat
import subprocess
import pytest
from tscan.cli import main
from tscan.git import get_staged_files, scan_staged
from tscan.hooks import HOOK_SIGNATURE, install_hook, uninstall_hook


def init_git_repo(path: Path):
    """Helper to initialize a git repo with dummy user config."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)


def test_staged_detection_and_exit_code(tmp_path: Path, monkeypatch):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    # 1. Staged clean file
    clean_file = tmp_path / "safe.txt"
    clean_file.write_text("Hello clean world\n", encoding="utf-8")
    subprocess.run(["git", "add", "safe.txt"], cwd=tmp_path, check=True)

    summary = scan_staged(tmp_path)
    assert len(summary.findings) == 0
    assert main(["staged"]) == 0

    # 2. Stage a fake secret
    fake_key = "sk-" + "test-" + "abcdefghijklmnopqrstuv12"
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text(f"api_key = '{fake_key}'\n", encoding="utf-8")
    subprocess.run(["git", "add", "secret.txt"], cwd=tmp_path, check=True)

    summary = scan_staged(tmp_path)
    assert len(summary.findings) == 1
    assert summary.findings[0].kind == "openai_key"
    assert fake_key not in summary.findings[0].masked
    assert main(["staged"]) == 1

    # 3. Unstage secret file
    subprocess.run(["git", "rm", "--cached", "secret.txt"], cwd=tmp_path, check=True)
    assert main(["staged"]) == 0


def test_staged_inspects_git_index_not_working_tree(tmp_path: Path):
    # R5: Must inspect git show :<path>, not current working tree file
    init_git_repo(tmp_path)
    fake_key = "sk-" + "test-" + "abcdefghijklmnopqrstuv12"

    target_file = tmp_path / "app.py"
    target_file.write_text("initial = 'clean'\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)

    # Modify in working tree without staging: index is clean!
    target_file.write_text(f"leak = '{fake_key}'\n", encoding="utf-8")
    summary = scan_staged(tmp_path)
    assert len(summary.findings) == 0

    # Stage the secret
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    summary = scan_staged(tmp_path)
    assert len(summary.findings) == 1

    # Now clean the working tree without staging: index still has secret!
    target_file.write_text("reverted = 'clean'\n", encoding="utf-8")
    summary = scan_staged(tmp_path)
    assert len(summary.findings) == 1


def test_hook_install_uninstall(tmp_path: Path):
    # R6: install-hook and uninstall-hook
    init_git_repo(tmp_path)

    hook_path = tmp_path / ".git" / "hooks" / "pre-commit"
    assert not hook_path.exists()

    success, msg = install_hook(tmp_path)
    assert success is True
    assert hook_path.exists()
    assert HOOK_SIGNATURE in hook_path.read_text(encoding="utf-8")

    # Check executable bit
    mode = hook_path.stat().st_mode
    assert mode & stat.S_IXUSR

    # Uninstall
    success, msg = uninstall_hook(tmp_path)
    assert success is True
    assert not hook_path.exists()


def test_hook_preserves_existing_custom_hook(tmp_path: Path):
    # R6: Existing non-tscan hooks must be protected
    init_git_repo(tmp_path)

    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "pre-commit"

    custom_script = "#!/bin/sh\necho 'custom tool running'\nexit 0\n"
    hook_path.write_text(custom_script, encoding="utf-8")

    # Install should refuse to overwrite
    success, msg = install_hook(tmp_path)
    assert success is False
    assert "not managed by tscan" in msg
    assert hook_path.read_text(encoding="utf-8") == custom_script

    # Uninstall should refuse to delete
    success, msg = uninstall_hook(tmp_path)
    assert success is False
    assert hook_path.exists()
    assert hook_path.read_text(encoding="utf-8") == custom_script


def test_hook_blocks_git_commit_on_secret(tmp_path: Path, monkeypatch):
    init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    # Make sure 'tscan' command in hook calls current python module via a helper script or wrapper
    # In hook: tries tscan staged or uv run tscan staged.
    # To test pre-commit hook execution directly with git commit, we can install the hook,
    # and provide a mock/shim in PATH or invoke pre-commit directly.
    install_hook(tmp_path)
    hook_path = tmp_path / ".git" / "hooks" / "pre-commit"

    # Replace hook invocation to invoke sys.executable -m tscan.cli staged directly
    import sys
    test_hook_script = f"""#!/bin/sh
{HOOK_SIGNATURE}
"{sys.executable}" -m tscan.cli staged
"""
    hook_path.write_text(test_hook_script, encoding="utf-8")
    hook_path.chmod(0o755)

    # 1. Clean commit should succeed
    clean_file = tmp_path / "hello.txt"
    clean_file.write_text("Hello clean commit\n", encoding="utf-8")
    subprocess.run(["git", "add", "hello.txt"], cwd=tmp_path, check=True)
    commit_res = subprocess.run(["git", "commit", "-m", "Clean commit"], cwd=tmp_path, capture_output=True)
    assert commit_res.returncode == 0

    # 2. Secret commit should be blocked (returncode != 0)
    fake_key = "sk-" + "test-" + "1234567890123456789012"
    bad_file = tmp_path / "bad.txt"
    bad_file.write_text(f"secret={fake_key}\n", encoding="utf-8")
    subprocess.run(["git", "add", "bad.txt"], cwd=tmp_path, check=True)
    blocked_commit = subprocess.run(["git", "commit", "-m", "Secret leak"], cwd=tmp_path, capture_output=True)
    assert blocked_commit.returncode != 0
    # Commit must not have taken place
    log_res = subprocess.run(["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True)
    assert "Secret leak" not in log_res.stdout
