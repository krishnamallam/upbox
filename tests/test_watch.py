"""Tests for upbox/watch.py — the rule-file poll watcher."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from upbox.addons.enforce import EnforceAddon
from upbox.addons.fingerprint import FingerprintAddon
from upbox.addons.redact import RedactAddon
from upbox.watch import RuleReloadWatcher, build_rule_watch_targets, watch_rules

# A timestamp far in the future, used to force a detectable mtime change
# without depending on filesystem mtime resolution.
_FUTURE = 2_000_000_000.0


async def _wait_until(predicate, timeout: float = 1.0) -> bool:
    elapsed = 0.0
    while elapsed < timeout:
        if predicate():
            return True
        await asyncio.sleep(0.01)
        elapsed += 0.01
    return predicate()


async def test_watch_reloads_on_mtime_change(tmp_path: Path) -> None:
    f = tmp_path / "r.yaml"
    f.write_text("v1")
    fired: list[int] = []
    task = asyncio.create_task(watch_rules([(f, lambda: fired.append(1))], poll_interval=0.01))

    f.write_text("v2")
    os.utime(f, (_FUTURE, _FUTURE))
    ok = await _wait_until(lambda: bool(fired))
    task.cancel()

    assert ok


async def test_watch_ignores_unchanged_file(tmp_path: Path) -> None:
    f = tmp_path / "r.yaml"
    f.write_text("v1")
    fired: list[int] = []
    task = asyncio.create_task(watch_rules([(f, lambda: fired.append(1))], poll_interval=0.01))

    await asyncio.sleep(0.05)
    task.cancel()

    assert fired == []


async def test_watch_isolates_per_file(tmp_path: Path) -> None:
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text("a1")
    b.write_text("b1")
    fired_a: list[int] = []
    fired_b: list[int] = []
    task = asyncio.create_task(
        watch_rules(
            [(a, lambda: fired_a.append(1)), (b, lambda: fired_b.append(1))],
            poll_interval=0.01,
        )
    )

    b.write_text("b2")
    os.utime(b, (_FUTURE, _FUTURE))
    fired_b_first = await _wait_until(lambda: bool(fired_b))
    task.cancel()

    assert fired_b_first and fired_a == []


async def test_watch_reloads_on_first_appearance(tmp_path: Path) -> None:
    f = tmp_path / "r.yaml"  # does not exist yet (user's first dashboard save)
    fired: list[int] = []
    task = asyncio.create_task(watch_rules([(f, lambda: fired.append(1))], poll_interval=0.01))

    f.write_text("v1")
    os.utime(f, (_FUTURE, _FUTURE))
    ok = await _wait_until(lambda: bool(fired))
    task.cancel()

    assert ok


async def test_watch_survives_raising_reloader(tmp_path: Path) -> None:
    f = tmp_path / "r.yaml"
    f.write_text("v1")
    fired: list[str] = []

    def reloader() -> None:
        fired.append("call")
        if len(fired) == 1:
            raise RuntimeError("synthetic")

    task = asyncio.create_task(watch_rules([(f, reloader)], poll_interval=0.01))

    f.write_text("v2")
    os.utime(f, (_FUTURE, _FUTURE))
    await _wait_until(lambda: len(fired) >= 1)
    f.write_text("v3")
    os.utime(f, (_FUTURE + 10, _FUTURE + 10))
    ok = await _wait_until(lambda: len(fired) >= 2)
    task.cancel()

    assert ok


def test_build_targets_pairs_each_addon_path_with_its_reload() -> None:
    from upbox.addons import enforce, fingerprint, redact

    fp = FingerprintAddon()
    rd = RedactAddon()
    en = EnforceAddon()

    targets = build_rule_watch_targets(fp, rd, en)

    assert targets == [
        (fingerprint.USER_RULES_PATH, fp.reload),
        (redact.USER_RULES_PATH, rd.reload),
        (enforce.USER_RULES_PATH, en.reload),
    ]


async def test_watcher_running_starts_task_and_done_cancels() -> None:
    watcher = RuleReloadWatcher([])
    watcher.running()
    started = watcher._task is not None and not watcher._task.done()

    watcher.done()
    await asyncio.sleep(0)  # let the cancellation propagate

    assert started and watcher._task is not None and watcher._task.cancelled()
