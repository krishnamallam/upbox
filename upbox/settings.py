"""User settings — YAML rule files under ``~/.upbox/rules/``.

The redact and fingerprint addons prefer this directory over the bundled
defaults when present. The dashboard settings page writes here on submit.
``yaml.safe_load`` plus a shape check prevents anything weird from landing
on disk.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

import yaml

USER_RULES_DIR = Path.home() / ".upbox" / "rules"

# (rule kind, expected top-level type after safe_load).
SCHEMAS: dict[str, type] = {
    "tools": list,
    "redact": list,
    "allowlist": dict,
}


def user_path(kind: str) -> Path:
    return USER_RULES_DIR / f"{kind}.yaml"


def read_current(kind: str) -> str:
    """Return the current user rule text, or the bundled default if no override."""
    path = user_path(kind)
    if path.exists():
        return path.read_text()
    return resources.files("upbox.rules").joinpath(f"{kind}.yaml").read_text()


def validate_and_write(kind: str, raw_text: str) -> tuple[bool, str]:
    """Validate the submitted YAML and persist it. Returns ``(ok, message)``."""
    if kind not in SCHEMAS:
        return False, f"unknown rule kind: {kind!r}"
    try:
        parsed = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        return False, f"YAML parse failed: {exc}"
    expected = SCHEMAS[kind]
    if not isinstance(parsed, expected):
        return False, f"top-level shape must be {expected.__name__}, got {type(parsed).__name__}"
    if not _structurally_valid(kind, parsed):
        return False, f"{kind}.yaml failed structural validation"
    USER_RULES_DIR.mkdir(parents=True, exist_ok=True)
    user_path(kind).write_text(raw_text)
    return True, f"saved to {user_path(kind)}"


def _structurally_valid(kind: str, parsed: Any) -> bool:
    """Light schema checks. Doesn't enforce every field, just the basics."""
    if kind in {"tools", "redact"}:
        if not isinstance(parsed, list):
            return False
        for entry in parsed:
            if not isinstance(entry, dict) or "name" not in entry:
                return False
            if kind == "redact" and "pattern" not in entry:
                return False
        return True
    if kind == "allowlist":
        if not isinstance(parsed, dict):
            return False
        for tool, entry in parsed.items():
            if not isinstance(tool, str) or not isinstance(entry, dict):
                return False
        return True
    return False
