"""Destinations upbox must never decrypt.

Loaded into mitmproxy's ``ignore_hosts``, which tunnels matching connections
without generating a certificate or reading a body. This takes effect regardless
of the TLS allowlist and regardless of ``--capture-all``, which is the point:
the allowlist is a capture policy and can be widened, while this is a floor.

Deploying upbox across a workforce means intercepting employees' TLS. Article 29
Working Party Opinion 2/2017 on data processing at work treats blanket
inspection of all communications as hard to justify and calls for excluding
categories such as private webmail, banking and health from interception by
configuration. This list is that control, shipped on by default rather than left
as an exercise.
"""

from __future__ import annotations

import logging
import re
from importlib import resources
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

DEFAULT_RULES_RESOURCE = "no_intercept.yaml"
USER_RULES_PATH = Path.home() / ".upbox" / "rules" / "no_intercept.yaml"


def load_no_intercept_patterns() -> list[str]:
    """Return the never-decrypt regexes, falling back to the bundled defaults.

    A broken user file falls back to the defaults rather than to an empty list.
    Failing open here would silently start decrypting banking traffic, so the
    safe direction is unambiguous.
    """
    try:
        if USER_RULES_PATH.exists():
            raw = yaml.safe_load(USER_RULES_PATH.read_text())
            patterns = _validate(raw)
            if patterns:
                return patterns
            log.warning("no_intercept.yaml is empty or invalid; using bundled defaults")
    except Exception:
        log.exception("no_intercept.yaml is unreadable; using bundled defaults")
    return _validate(
        yaml.safe_load(resources.files("upbox.rules").joinpath(DEFAULT_RULES_RESOURCE).read_text())
    )


def _validate(raw: object) -> list[str]:
    """Keep the entries that are strings and compile as regexes."""
    if not isinstance(raw, list):
        return []
    patterns: list[str] = []
    for entry in raw:
        if not isinstance(entry, str):
            log.warning("ignoring non-string no_intercept entry: %r", entry)
            continue
        try:
            re.compile(entry)
        except re.error:
            log.warning("ignoring uncompilable no_intercept pattern: %r", entry)
            continue
        patterns.append(entry)
    return patterns
