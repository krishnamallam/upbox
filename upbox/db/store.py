"""SQLite-backed audit log store for upbox.

One row per AI tool request. WAL mode is enforced at open so the proxy
process (single writer) and the dashboard process (readers) can share the
file without blocking each other.

Schema lives in ``upbox/db/schema.sql`` and is read via ``importlib.resources``
so the package can be installed as a wheel without losing the file.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields
from importlib import resources
from pathlib import Path
from typing import IO, Any

DEFAULT_DB_PATH = Path.home() / ".upbox" / "upbox.db"
BODY_EXCERPT_MAX = 4096


@dataclass(frozen=True)
class RequestRecord:
    """One row in the requests table.

    Fields filled in by later-day addons (``tool`` on Day 4, ``redactions_applied_json``
    on Day 7, ``blocked`` on Day 8) are ``None`` / 0 by default so Day 3 capture
    can build a record without knowing about them.
    """

    ts: str
    tool: str | None
    method: str
    scheme: str
    host: str
    path: str
    req_bytes: int
    resp_bytes: int | None
    status: int | None
    headers_json: str
    body_excerpt: str | None
    body_hash: str | None
    redactions_applied_json: str | None
    blocked: int


_INSERT_COLUMNS = (
    "ts, tool, method, scheme, host, path, req_bytes, resp_bytes, status, "
    "headers_json, body_excerpt, body_hash, redactions_applied_json, blocked"
)
_INSERT_PLACEHOLDERS = ", ".join("?" * 14)


class Store:
    """SQLite audit-log store. Open is idempotent."""

    def __init__(self, path: Path = DEFAULT_DB_PATH) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._enable_wal()

    def _init_schema(self) -> None:
        schema = resources.files("upbox.db").joinpath("schema.sql").read_text()
        self._conn.executescript(schema)

    def _enable_wal(self) -> None:
        row = self._conn.execute("PRAGMA journal_mode=WAL").fetchone()
        # In-memory databases silently refuse WAL and return "memory". That's
        # fine for tests. Anything else that isn't WAL is a real problem.
        actual = row[0].lower()
        if actual not in {"wal", "memory"}:
            raise RuntimeError(f"failed to enable WAL mode (got {actual!r})")

    def insert_request(self, record: RequestRecord) -> int:
        cursor = self._conn.execute(
            f"INSERT INTO requests ({_INSERT_COLUMNS}) VALUES ({_INSERT_PLACEHOLDERS})",
            (
                record.ts,
                record.tool,
                record.method,
                record.scheme,
                record.host,
                record.path,
                record.req_bytes,
                record.resp_bytes,
                record.status,
                record.headers_json,
                record.body_excerpt,
                record.body_hash,
                record.redactions_applied_json,
                record.blocked,
            ),
        )
        rowid = cursor.lastrowid
        if rowid is None:
            raise RuntimeError("insert returned no rowid")
        return rowid

    def query_recent(self, limit: int = 100) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM requests ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        )

    def iter_all(self) -> Iterator[sqlite3.Row]:
        yield from self._conn.execute("SELECT * FROM requests ORDER BY id")

    def export_jsonl(self, out: IO[str], rows: Iterable[sqlite3.Row] | None = None) -> int:
        """Write one JSON object per line. Returns the count written."""
        if rows is None:
            rows = self.iter_all()
        fieldnames = _csv_fieldnames()
        count = 0
        for row in rows:
            json.dump({name: row[name] for name in fieldnames}, out)
            out.write("\n")
            count += 1
        return count

    def export_csv(self, out: IO[str], rows: Iterable[sqlite3.Row] | None = None) -> int:
        """Write CSV with a header row. Returns the count of data rows written."""
        fieldnames = _csv_fieldnames()
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        rows_list = list(rows) if rows is not None else list(self.iter_all())
        for row in rows_list:
            writer.writerow({name: row[name] for name in fieldnames})
        return len(rows_list)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def truncate_body_excerpt(body: bytes | str | None) -> str | None:
    """Cap a request/response body for storage.

    Returns at most ``BODY_EXCERPT_MAX`` *bytes* worth of text, decoded as
    UTF-8 with ``errors="replace"``. Binary bodies become mostly Unicode
    replacement characters but ``body_hash`` is the source of truth for the
    actual content.
    """
    if body is None:
        return None
    raw = body if isinstance(body, bytes) else body.encode("utf-8", "replace")
    return raw[:BODY_EXCERPT_MAX].decode("utf-8", "replace")


def _csv_fieldnames() -> list[str]:
    """Column order for export: synthetic ``id`` then RequestRecord fields."""
    return ["id", *(f.name for f in fields(RequestRecord))]


@contextmanager
def open_store(path: Path = DEFAULT_DB_PATH) -> Iterator[Store]:
    store = Store(path)
    try:
        yield store
    finally:
        store.close()
