"""Retention policy for the audit log.

Two tiers, because prompt bodies and connection metadata carry very different
risk and very different evidentiary value.

``body_days`` clears the stored request body and headers while keeping the row.
This is the chain-safe tier: the hash chain commits to digests of those columns
rather than their text, so clearing them leaves verification intact and the row
still proves that a request of a given size went to a given host at a given
time, with a body that hashed to a given value.

``record_days`` deletes whole rows. That necessarily leaves a gap in the chain,
so every deletion is recorded in ``chain_gaps`` with the last deleted entry's
hash, which lets verification resume across the gap and report it as a
disclosed retention deletion rather than as tampering.

Defaults prune bodies after a week and never delete rows. Storage limitation
under GDPR Article 5(1)(e) pushes down, evidentiary value pushes up, and the
body is where the personal data almost always is.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    # Runtime import would be circular: store imports RetentionPolicy from here.
    from upbox.db.store import Store

log = logging.getLogger(__name__)

USER_POLICY_PATH = Path.home() / ".upbox" / "rules" / "retention.yaml"

DEFAULT_BODY_DAYS = 7
DEFAULT_MIN_RECORD_DAYS = 180


@dataclass(frozen=True)
class RetentionPolicy:
    """Resolved retention settings.

    ``None`` means "keep forever" for either tier. ``min_record_days`` is a
    soft floor: going below it warns and proceeds, because how long to keep an
    audit log is the controller's decision, not upbox's.
    """

    body_days: int | None = DEFAULT_BODY_DAYS
    record_days: int | None = None
    min_record_days: int = DEFAULT_MIN_RECORD_DAYS

    def body_cutoff(self, now: datetime) -> datetime | None:
        return None if self.body_days is None else now - timedelta(days=self.body_days)

    def record_cutoff(self, now: datetime) -> datetime | None:
        return None if self.record_days is None else now - timedelta(days=self.record_days)

    def warnings(self) -> list[str]:
        notes: list[str] = []
        if self.record_days is not None and self.record_days < self.min_record_days:
            notes.append(
                f"record_days={self.record_days} is below min_record_days="
                f"{self.min_record_days}. Deleting rows this early may cut into a "
                "retention period you are relying on for evidence. Proceeding anyway."
            )
        if (
            self.record_days is not None
            and self.body_days is not None
            and self.record_days < self.body_days
        ):
            notes.append(
                f"record_days={self.record_days} is below body_days={self.body_days}, "
                "so rows are deleted before their bodies are ever cleared. "
                "body_days has no effect."
            )
        return notes


def load_policy(path: Path | None = None) -> RetentionPolicy:
    """Read the policy file, falling back to defaults.

    A malformed file keeps the defaults rather than disabling retention or
    crashing the proxy, matching how the other rule files behave.
    """
    resolved = path if path is not None else USER_POLICY_PATH
    if not resolved.exists():
        return RetentionPolicy()
    try:
        raw = yaml.safe_load(resolved.read_text()) or {}
    except Exception:
        log.exception("retention.yaml is unreadable; using defaults")
        return RetentionPolicy()
    if not isinstance(raw, dict):
        log.warning("retention.yaml is not a mapping; using defaults")
        return RetentionPolicy()
    try:
        return RetentionPolicy(
            body_days=_optional_days(raw, "body_days", DEFAULT_BODY_DAYS),
            record_days=_optional_days(raw, "record_days", None),
            min_record_days=int(raw.get("min_record_days", DEFAULT_MIN_RECORD_DAYS)),
        )
    except (TypeError, ValueError):
        log.exception("retention.yaml has invalid values; using defaults")
        return RetentionPolicy()


def _optional_days(raw: dict[str, object], key: str, default: int | None) -> int | None:
    if key not in raw:
        return default
    value = raw[key]
    if value is None:
        return None
    days = int(value)  # type: ignore[call-overload,unused-ignore]
    if not isinstance(days, int):  # pragma: no cover - defensive against odd YAML scalars
        raise TypeError(f"{key} must be an integer")
    if days < 0:
        raise ValueError(f"{key} must not be negative")
    return days


def utcnow() -> datetime:
    return datetime.now(UTC)


# One pass a day is enough: the cutoffs are in days, so a tighter interval just
# re-scans rows it already cleared. The first pass runs at proxy start, which is
# also what catches a machine that is off overnight.
RETENTION_INTERVAL_SECONDS = 24 * 60 * 60


class RetentionRunner:
    """mitmproxy addon: applies the retention policy on the proxy's event loop.

    Retention runs in the proxy process only. It is a write, and the hash chain
    is only sound with a single writer.
    """

    def __init__(self, store: Store, interval: float = RETENTION_INTERVAL_SECONDS) -> None:
        self._store = store
        self._interval = interval
        self._task: asyncio.Task[None] | None = None

    def running(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())
        self._task.add_done_callback(self._on_done)

    def done(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            self.run_once()
            await asyncio.sleep(self._interval)

    def run_once(self) -> None:
        """Apply the policy, re-reading it each pass so edits take effect.

        Never raises: a failed retention pass must not take the proxy down.
        """
        try:
            policy = load_policy()
            for note in policy.warnings():
                log.warning("retention: %s", note)
            result = self._store.prune(policy)
        except Exception:
            log.exception("retention pass failed; the audit log is unchanged")
            return
        if result.bodies_cleared or result.records_deleted:
            log.info(
                "retention: cleared %d body/header set(s), deleted %d row(s)",
                result.bodies_cleared,
                result.records_deleted,
            )
            self._store.write_checkpoint("prune")

    @staticmethod
    def _on_done(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("retention runner exited unexpectedly: %r", exc)
