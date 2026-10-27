from __future__ import annotations

import os
from pathlib import Path
import re
import tomllib


def load_custom_rules(root_path: Path | None = None) -> list[tuple[str, re.Pattern]]:
    """Load custom regex rules from ~/.tscan/rules.toml and .tscan.toml."""
    rules: list[tuple[str, re.Pattern]] = []
    candidates: list[Path] = []

    # 1. User machine global config: ~/.tscan/rules.toml
    home_config = Path.home() / ".tscan" / "rules.toml"
    if home_config.exists() and home_config.is_file():
        candidates.append(home_config)

    # 2. Project local config: .tscan.toml in root_path (or cwd)
    if root_path:
        proj_config = (root_path if root_path.is_dir() else root_path.parent) / ".tscan.toml"
        if proj_config.exists() and proj_config.is_file():
            candidates.append(proj_config)
    else:
        proj_config = Path(".tscan.toml")
        if proj_config.exists() and proj_config.is_file():
            candidates.append(proj_config)

    for config_file in candidates:
        try:
            with open(config_file, "rb") as f:
                data = tomllib.load(f)
                rule_list = data.get("rules", [])
                for r in rule_list:
                    name = r.get("name")
                    pattern_str = r.get("pattern")
                    if name and pattern_str:
                        compiled = re.compile(pattern_str)
                        rules.append((name, compiled))
        except Exception:
            pass

    return rules
