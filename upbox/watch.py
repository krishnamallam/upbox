"""Live-reload of rule files for the running proxy.

A poll loop on mitmproxy's event loop watches each rule file's mtime and
calls the matching addon ``reload()`` when it changes — so dashboard edits
to ``tools.yaml`` / ``redact.yaml`` / ``allowlist.yaml`` apply without an
``upbox start`` restart. Reloading the TLS interception set (``allow_hosts``)
is out of scope: a brand-new intercepted host still needs a restart.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from pathlib import Path

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
