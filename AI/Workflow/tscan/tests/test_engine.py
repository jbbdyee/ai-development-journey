import io
from pathlib import Path
import pytest
from tscan.cli import main
from tscan.models import Finding
from tscan.scanner import scan_folder, scan_text


def test_scan_text_detects_all_secret_types():
    # Construct fake secrets dynamically to avoid static detection in source files
    fake_key = "sk-" + "test-" + "abcdefghijklmnopqrstuvwxyz12"
    fake_phone = "010-" + "1234-" + "5678"
    fake_email = "tester" + "@" + "example.com"
    fake_rrn = "900101-" + "1234567"

    content = f"""
    # Configuration
    api_key = "{fake_key}"
    contact = "{fake_phone}"
    admin_email = "{fake_email}"
    resident = "{fake_rrn}"
    """

    findings = scan_text(content, "sample.py")
    kinds = [f.kind for f in findings]

    assert "openai_key" in kinds
    assert "phone" in kinds
    assert "email" in kinds
    assert "rrn" in kinds

    # Verify masking and zero-retention
    for f in findings:
        assert not hasattr(f, "raw_value")
        assert not hasattr(f, "secret")
        assert fake_key not in f.masked
        assert fake_phone not in f.masked
        assert fake_email not in f.masked
        assert fake_rrn not in f.masked
        # Previews should also not leak the full secrets
        assert fake_key not in f.preview


def test_false_positive_prevention():
    # R4: Dates, versions, and order numbers should not be detected
    content = """
    build_date = 2026-10-27
    version = 1.0.10-20261027
    order_id = 202610271234
    release_date = 2025.12.31
    """

    findings = scan_text(content, "info.txt")
    assert len(findings) == 0, f"Expected 0 findings but got: {findings}"


def test_env_value_detection(tmp_path: Path):
    # R3: .env value >= 6 chars should be detected in another file as env_value
    fake_token = "secret" + "Token" + "98765"
    env_file = tmp_path / ".env"
    env_file.write_text(f"API_SECRET={fake_token}\nDEBUG=true\n", encoding="utf-8")

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    app_file = src_dir / "app.py"
    app_file.write_text(f'auth_header = "Bearer {fake_token}"\n', encoding="utf-8")

    summary = scan_folder(tmp_path)
    env_findings = [f for f in summary.findings if f.kind == "env_value"]

    assert len(env_findings) == 1
    assert env_findings[0].kind == "env_value"
    assert env_findings[0].path == "src/app.py" or env_findings[0].path == "src\\app.py"
    assert env_findings[0].masked == "[env_value]"
    assert fake_token not in env_findings[0].masked


def test_skip_rules(tmp_path: Path):
    # R13: .git, node_modules, .venv, large files (>1MB), and binaries (NUL byte)
    fake_key = "sk-" + "test-" + "abcdefghijklmnopqrstuvwxyz12"

    # 1. Ignored directory
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config.txt").write_text(f"key = {fake_key}\n", encoding="utf-8")

    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    (venv_dir / "lib.py").write_text(f"key = {fake_key}\n", encoding="utf-8")

    # 2. Binary file (contains NUL byte)
    bin_file = tmp_path / "image.png"
    bin_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + fake_key.encode())

    # 3. Large file (> 1MB)
    large_file = tmp_path / "large.txt"
    large_file.write_bytes(b"A" * (1024 * 1024 + 10) + fake_key.encode())

    # 4. Valid text file that should be scanned
    valid_file = tmp_path / "clean.txt"
    valid_file.write_text("All clean here.\n", encoding="utf-8")

    summary = scan_folder(tmp_path)

    # Secrets inside .git, .venv, binary, and large file should NOT be found
    assert len(summary.findings) == 0
    # Binary and large file should be counted in skipped_files
    assert summary.skipped_files >= 2
    assert summary.scanned_files >= 1


def test_cli_plain_output(tmp_path: Path, monkeypatch, capsys):
    fake_key = "sk-" + "test-" + "abcdefghijklmnopqrst"
    fake_phone = "010-" + "0000-" + "0000"

    test_file = tmp_path / "a.txt"
    test_file.write_text(
        f"key={fake_key}\ncall {fake_phone}\ndate 2026-10-27\n",
        encoding="utf-8",
    )

    exit_code = main(["scan", str(tmp_path), "--plain"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "openai_key" in captured.out
    assert "phone" in captured.out
    assert "date" not in captured.out
    # R2: Raw values must not appear anywhere in plain output
    assert "abcdefghijklmnopqrst" not in captured.out
    assert "sk-…****…" in captured.out
    assert "010-****-0000" in captured.out
