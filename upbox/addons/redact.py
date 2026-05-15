"""Content-aware redaction addon.

Per the eng-review Issue 3 decision, this is content-aware, not byte-level
regex on raw bodies. The pipeline:

1. Read ``request.content``. mitmproxy auto-decompresses gzip/brotli, so
   we see plain bytes regardless of ``Content-Encoding``.
2. Dispatch on ``Content-Type``:
   - ``application/json`` (or ``*+json``): parse, walk, redact every
     string value, re-serialise. JSON structure is preserved.
   - ``text/*``: byte-level regex with JSON-safe replacement.
   - anything else (binary, multipart, octet-stream): skip with a
     logged reason. Dashboard surfaces it via ``redactions_applied_json``.
3. Write back to ``request.content`` if anything was redacted. mitmproxy
   re-applies the original Content-Encoding.

Failures inside the addon are logged but never propagate, per CLAUDE.md.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from mitmproxy import http

log = logging.getLogger(__name__)

DEFAULT_RULES_RESOURCE = "redact.yaml"
USER_RULES_PATH = Path.home() / ".upbox" / "rules" / "redact.yaml"


@dataclass(frozen=True)
class RedactPattern:
    name: str
    regex: re.Pattern[str]
    replace: str


def _compile_patterns(raw: list[dict[str, Any]] | None) -> list[RedactPattern]:
    patterns: list[RedactPattern] = []
    for entry in raw or []:
        flags = re.MULTILINE if entry.get("multiline") else 0
        patterns.append(
            RedactPattern(
                name=str(entry["name"]),
                regex=re.compile(str(entry["pattern"]), flags),
                replace=str(entry["replace"]),
            )
        )
    return patterns


def load_patterns() -> list[RedactPattern]:
    if USER_RULES_PATH.exists():
        raw = yaml.safe_load(USER_RULES_PATH.read_text())
    else:
        raw = yaml.safe_load(
            resources.files("upbox.rules").joinpath(DEFAULT_RULES_RESOURCE).read_text()
        )
    return _compile_patterns(raw)


class RedactAddon:
    """Applies content-aware redactions to the request body before forwarding."""

    def __init__(self, patterns: list[RedactPattern] | None = None) -> None:
        self._patterns = patterns if patterns is not None else load_patterns()

    def request(self, flow: http.HTTPFlow) -> None:
        try:
            self._apply(flow)
        except Exception:
            log.exception("redact failed on flow %s", getattr(flow, "id", "<unknown>"))

    def _apply(self, flow: http.HTTPFlow) -> None:
        req = flow.request
        try:
            content = req.content
        except ValueError:
            # mitmproxy raises when Content-Encoding is set but not supported.
            self._mark_skipped(flow, "unsupported encoding")
            return

        if not content:
            return

        content_type = req.headers.get("content-type", "").lower()

        if "application/json" in content_type or "+json" in content_type:
            self._redact_json(flow, content)
        elif content_type.startswith("text/"):
            self._redact_text(flow, content)
        else:
            reason = f"binary or unsupported content-type: {content_type or '(none)'}"
            self._mark_skipped(flow, reason)

    def _redact_json(self, flow: http.HTTPFlow, content: bytes) -> None:
        try:
            obj = json.loads(content)
        except json.JSONDecodeError:
            self._mark_skipped(flow, "malformed JSON")
            return

        new_obj, applied = _walk_json(obj, self._patterns)
        if applied:
            flow.request.content = json.dumps(new_obj).encode("utf-8")
            self._mark_applied(flow, applied)

    def _redact_text(self, flow: http.HTTPFlow, content: bytes) -> None:
        text = content.decode("utf-8", "replace")
        new_text, applied = _redact_string(text, self._patterns)
        if applied:
            flow.request.content = new_text.encode("utf-8")
            self._mark_applied(flow, applied)

    @staticmethod
    def _mark_applied(flow: http.HTTPFlow, applied: list[str]) -> None:
        flow.metadata["upbox_redactions"] = {"applied": applied}

    @staticmethod
    def _mark_skipped(flow: http.HTTPFlow, reason: str) -> None:
        flow.metadata["upbox_redactions"] = {"skipped": reason}


def _redact_string(text: str, patterns: list[RedactPattern]) -> tuple[str, list[str]]:
    applied: list[str] = []
    for pattern in patterns:
        new_text, count = pattern.regex.subn(pattern.replace, text)
        if count:
            applied.extend([pattern.name] * count)
            text = new_text
    return text, applied


def _walk_json(obj: Any, patterns: list[RedactPattern]) -> tuple[Any, list[str]]:
    if isinstance(obj, str):
        new_text, applied = _redact_string(obj, patterns)
        return new_text, applied
    if isinstance(obj, list):
        out_list: list[Any] = []
        all_applied: list[str] = []
        for item in obj:
            new_item, applied = _walk_json(item, patterns)
            out_list.append(new_item)
            all_applied.extend(applied)
        return out_list, all_applied
    if isinstance(obj, dict):
        out_dict: dict[Any, Any] = {}
        all_applied = []
        for key, value in obj.items():
            new_value, applied = _walk_json(value, patterns)
            out_dict[key] = new_value
            all_applied.extend(applied)
        return out_dict, all_applied
    return obj, []
