import re
from tscan.patterns import PATTERNS


def mask_openai_key(val: str) -> str:
    """Mask OpenAI key as sk-…****…xx"""
    if len(val) >= 6 and val.startswith("sk-"):
        return f"sk-…****…{val[-2:]}"
    return "***"


def mask_phone(val: str) -> str:
    """Mask Korean mobile phone as 010-****-xxxx"""
    digits = re.sub(r"\D", "", val)
    if len(digits) >= 10:
        prefix = digits[:3]
        suffix = digits[-4:]
        return f"{prefix}-****-{suffix}"
    return "***"


def mask_email(val: str) -> str:
    """Mask email as u***@domain"""
    if "@" in val:
        local, domain = val.split("@", 1)
        first_char = local[0] if local else ""
        return f"{first_char}***@{domain}"
    return "***"


def mask_rrn(val: str) -> str:
    """Mask Resident Registration Number as xxxxxx-*******"""
    digits = re.sub(r"\D", "", val)
    if len(digits) >= 13:
        return f"{digits[:6]}-*******"
    if len(val) >= 6:
        return f"{val[:6]}-*******"
    return "***"


def mask_env_value(val: str) -> str:
    """Mask .env value without revealing any part of it."""
    return "[env_value]"


def mask_value(kind: str, raw_val: str) -> str:
    if kind == "openai_key":
        return mask_openai_key(raw_val)
    elif kind == "phone":
        return mask_phone(raw_val)
    elif kind == "email":
        return mask_email(raw_val)
    elif kind == "rrn":
        return mask_rrn(raw_val)
    elif kind == "env_value":
        return mask_env_value(raw_val)
    else:
        # Custom rule masking (e.g., employee id E-123456 -> E-***56)
        if len(raw_val) >= 4:
            return f"{raw_val[:2]}***{raw_val[-2:]}"
        return "***"


def mask_line(
    line: str,
    env_values: set[str] | None = None,
    custom_patterns: list[tuple[str, re.Pattern]] | None = None,
) -> str:
    """Mask all detected secrets in a single line of text."""
    masked_line = line
    all_patterns = list(PATTERNS) + (custom_patterns or [])

    for kind, pattern in all_patterns:
        def repl(match: re.Match) -> str:
            raw = match.group(1) if match.lastindex else match.group(0)
            return mask_value(kind, raw)
        masked_line = pattern.sub(repl, masked_line)

    if env_values:
        for val in sorted(env_values, key=len, reverse=True):
            if val in masked_line:
                masked_line = masked_line.replace(val, mask_env_value(val))

    return masked_line
