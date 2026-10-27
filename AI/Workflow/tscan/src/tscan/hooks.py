import os
from pathlib import Path
import stat
from tscan.git import get_git_dir

HOOK_SIGNATURE = "# Managed by tscan"

HOOK_TEMPLATE = """#!/bin/sh
# Managed by tscan
# Pre-commit hook to prevent committing secrets

if command -v tscan >/dev/null 2>&1; then
    tscan staged
elif [ -d "$HOME/.local/bin" ] && [ -x "$HOME/.local/bin/tscan" ]; then
    "$HOME/.local/bin/tscan" staged
elif [ -f "pyproject.toml" ] && grep -q 'name = "tscan"' "pyproject.toml" 2>/dev/null; then
    uv run tscan staged
else
    echo "Error: 'tscan' command not found in PATH. Please install it with 'uv tool install --editable <path/to/tscan>'." >&2
    exit 1
fi
"""


def install_hook(repo_path: Path | str | None = None) -> tuple[bool, str]:
    """Install tscan pre-commit hook into .git/hooks/pre-commit.

    If a pre-commit hook exists and does not contain the tscan signature,
    installation is rejected to preserve existing tools.
    """
    git_dir = get_git_dir(repo_path)
    if not git_dir:
        return False, "Error: Not a git repository."

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_file = hooks_dir / "pre-commit"

    if hook_file.exists():
        try:
            content = hook_file.read_text(encoding="utf-8", errors="ignore")
            if HOOK_SIGNATURE not in content:
                return (
                    False,
                    f"Existing pre-commit hook found at '{hook_file}' not managed by tscan. Aborting installation.",
                )
        except OSError as e:
            return False, f"Failed to read existing hook: {e}"

    try:
        hook_file.write_text(HOOK_TEMPLATE, encoding="utf-8")
        # Ensure executable permissions: rwxr-xr-x (0o755)
        current_mode = hook_file.stat().st_mode
        hook_file.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return True, f"tscan pre-commit hook installed at '{hook_file}'."
    except OSError as e:
        return False, f"Failed to write hook file: {e}"


def uninstall_hook(repo_path: Path | str | None = None) -> tuple[bool, str]:
    """Uninstall tscan pre-commit hook.

    Only hooks containing the tscan signature will be removed.
    """
    git_dir = get_git_dir(repo_path)
    if not git_dir:
        return False, "Error: Not a git repository."

    hook_file = git_dir / "hooks" / "pre-commit"
    if not hook_file.exists():
        return False, f"No pre-commit hook found at '{hook_file}'."

    try:
        content = hook_file.read_text(encoding="utf-8", errors="ignore")
        if HOOK_SIGNATURE not in content:
            return (
                False,
                f"Existing pre-commit hook at '{hook_file}' is not managed by tscan. Aborting uninstall.",
            )
        hook_file.unlink()
        return True, f"tscan pre-commit hook removed from '{hook_file}'."
    except OSError as e:
        return False, f"Failed to remove hook file: {e}"
