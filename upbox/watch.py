"""Live-reload of rule files for the running proxy.

A poll loop on mitmproxy's event loop watches each rule file's mtime and
calls the matching addon ``reload()`` when it changes — so dashboard edits
to ``tools.yaml`` / ``redact.yaml`` / ``allowlist.yaml`` / ``capture.yaml`` apply without an
``upbox start`` restart. Reloading the TLS interception set (``allow_hosts``)
is out of scope: a brand-new intercepted host still needs a restart.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from upbox.addons.capture import CaptureAddon
    from upbox.addons.enforce import EnforceAddon
    from upbox.addons.fingerprint import FingerprintAddon
    from upbox.addons.redact import RedactAddon

log = logging.getLogger(__name__)

Target = tuple[Path, Callable[[], None]]


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return None


def watch_rules(targets: list[Target], poll_interval: float = 1.0) -> Coroutine[None, None, None]:
    """Poll each ``(path, reload_fn)`` and call ``reload_fn`` when the file changes.

    Records each file's mtime at call time (the proxy already loaded current
    config at boot), then reacts only to later changes. A ``None -> mtime``
    transition (first dashboard save creating the file) counts as a change.
    A ``reload_fn`` that raises is logged and never breaks the loop.

    Returns a coroutine suitable for ``asyncio.create_task``. The initial mtime
    snapshot is taken synchronously when this function is called — before the
    coroutine is scheduled — so any file changes after the call are detected.
    """
    last: dict[Path, float | None] = {path: _mtime(path) for path, _ in targets}

    async def _loop() -> None:
        while True:
            await asyncio.sleep(poll_interval)
            for path, reload_fn in targets:
                current = _mtime(path)
                if current == last.get(path):
                    continue
                last[path] = current
                if current is None:
                    continue  # file deleted — keep the previously-loaded config
                try:
                    reload_fn()
                except Exception:
                    log.exception("rule reload failed for %s", path)

    return _loop()


def build_rule_watch_targets(
    fingerprint: FingerprintAddon,
    redact: RedactAddon,
    enforce: EnforceAddon,
    capture: CaptureAddon,
) -> list[Target]:
    """Pair each rule file (each addon module's own path constant) with its reload."""
    from upbox.addons import capture as capture_mod
    from upbox.addons import enforce as enforce_mod
    from upbox.addons import fingerprint as fingerprint_mod
    from upbox.addons import redact as redact_mod

    return [
        (fingerprint_mod.USER_RULES_PATH, fingerprint.reload),
        (redact_mod.USER_RULES_PATH, redact.reload),
        (enforce_mod.USER_RULES_PATH, enforce.reload),
        (capture_mod.USER_RULES_PATH, capture.reload),
    ]


class RuleReloadWatcher:
    """mitmproxy addon: runs the rule-file watcher on the proxy's event loop."""

    def __init__(self, targets: list[Target], poll_interval: float = 1.0) -> None:
        self._targets = targets
        self._poll_interval = poll_interval
        self._task: asyncio.Task[None] | None = None

    def running(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(watch_rules(self._targets, self._poll_interval))
        self._task.add_done_callback(self._on_done)

    def done(self) -> None:
        if self._task is not None:
            self._task.cancel()

    @staticmethod
    def _on_done(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("rule watcher exited unexpectedly: %r", exc)
