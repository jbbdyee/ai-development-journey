import asyncio
from pathlib import Path
import pytest
from textual.widgets import DataTable, Static
from tscan.app import TScanApp


def test_tui_app_mount_and_preview(tmp_path: Path):
    fake_key = "sk-" + "test-" + "abcdefghijklmnopqrstuv12"
    fake_phone = "010-" + "9876-" + "5432"

    test_file = tmp_path / "leak.txt"
    test_file.write_text(
        f"line1_intro\nkey={fake_key}\nphone={fake_phone}\nline4_end\n",
        encoding="utf-8",
    )

    async def run_check():
        app = TScanApp(target_path=tmp_path)
        async with app.run_test() as pilot:
            # Wait for background worker to complete scan
            table = app.query_one("#findings_table", DataTable)
            summary_bar = app.query_one("#summary_bar", Static)
            preview_content = app.query_one("#preview_content", Static)

            # Wait briefly for worker if needed
            for _ in range(50):
                if table.row_count == 2:
                    break
                await pilot.pause(0.05)

            assert table.row_count == 2
            assert "찾은 것 2" in str(summary_bar.render())

            # Verify preview for first selected finding (key)
            preview_text = str(preview_content.render())
            assert "line1_intro" in preview_text
            assert "sk-…****…" in preview_text
            # Crucial: other secret (phone) in the same preview MUST also be masked!
            assert "010-****-5432" in preview_text
            # Raw secrets must never appear
            assert fake_key not in preview_text
            assert fake_phone not in preview_text

            # Move cursor down to second finding (phone)
            await pilot.press("down")
            await pilot.pause(0.05)

            preview_text_2 = str(preview_content.render())
            # Crucial: in the preview of the phone finding, the key on line 2 MUST also be masked!
            assert "sk-…****…" in preview_text_2
            assert "010-****-5432" in preview_text_2
            assert fake_key not in preview_text_2

            # Quit app with 'q'
            await pilot.press("q")

    asyncio.run(run_check())


def test_tui_clean_directory(tmp_path: Path):
    clean_file = tmp_path / "clean.txt"
    clean_file.write_text("Hello clean world\nNo secrets here.\n", encoding="utf-8")

    async def run_check():
        app = TScanApp(target_path=tmp_path)
        async with app.run_test() as pilot:
            table = app.query_one("#findings_table", DataTable)
            summary_bar = app.query_one("#summary_bar", Static)
            preview_content = app.query_one("#preview_content", Static)

            for _ in range(50):
                if "찾은 것 0" in str(summary_bar.render()):
                    break
                await pilot.pause(0.05)

            assert table.row_count == 0
            assert "찾은 것 0" in str(summary_bar.render())
            assert "안전합니다" in str(preview_content.render())

            await pilot.press("q")

    asyncio.run(run_check())


def test_tui_stage2_ignore_and_rescan(tmp_path: Path):
    fake_key = "sk-" + "test-" + "abcdefghijklmnopqrstuv12"
    fake_phone = "010-" + "1234-" + "5678"

    f = tmp_path / "secret.txt"
    f.write_text(f"key = '{fake_key}'\nphone = '{fake_phone}'\n", encoding="utf-8")

    async def run_check():
        app = TScanApp(target_path=tmp_path)
        async with app.run_test() as pilot:
            table = app.query_one("#findings_table", DataTable)

            # Wait for 2 findings
            for _ in range(50):
                if table.row_count == 2:
                    break
                await pilot.pause(0.05)

            assert table.row_count == 2

            # Press 'i' to ignore first finding
            await pilot.press("i")

            # Wait for rescan to reduce to 1 finding
            for _ in range(50):
                if table.row_count == 1:
                    break
                await pilot.pause(0.05)

            assert table.row_count == 1
            # Check .tscanignore was created
            ignore_file = tmp_path / ".tscanignore"
            assert ignore_file.exists()
            assert "secret.txt:1" in ignore_file.read_text(encoding="utf-8")

            # Press 'r' for manual rescan
            await pilot.press("r")
            await pilot.pause(0.1)
            assert table.row_count == 1

            await pilot.press("q")

    asyncio.run(run_check())
