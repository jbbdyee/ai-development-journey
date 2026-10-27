import re

# R1, R2, R4 pattern definitions with boundary conditions to eliminate false positives
PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "openai_key",
        re.compile(r"(?<![a-zA-Z0-9_-])(sk-[a-zA-Z0-9_-]{20,})(?![a-zA-Z0-9_-])"),
    ),
    (
        "rrn",
        re.compile(
            r"(?<![0-9a-zA-Z])(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[- ]?[1-4]\d{6})(?![0-9a-zA-Z])"
        ),
    ),
    (
        "phone",
        re.compile(
            r"(?<![0-9a-zA-Z.])(01[016789](?:-\d{3,4}-\d{4}|\.\d{3,4}\.\d{4}|\s\d{3,4}\s\d{4}|\d{7,8}))(?![0-9a-zA-Z.])"
        ),
    ),
    (
        "email",
        re.compile(
            r"(?<![0-9a-zA-Z_.+-])([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)(?![0-9a-zA-Z_.+-])"
        ),
    ),
]
