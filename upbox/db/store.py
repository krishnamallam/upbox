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
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import IO, Any, cast

from upbox.atrest import harden_path_permissions
from upbox.db import chain
from upbox.retention import RetentionPolicy

DEFAULT_DB_PATH = Path.home() / ".upbox" / "upbox.db"

# Bumped whenever _migrate gains a step. Fresh databases are created at the
# final shape by schema.sql and then run every migration anyway; each one is
# guarded so it is a no-op on an already-correct schema.
SCHEMA_VERSION = 3

# Columns added by the v2 hash-chain migration, with their affinities. seq must
# be INTEGER: under TEXT affinity SQLite would store 10 as '10' and order it
# before 9.
_V2_CHAIN_COLUMNS = {
    "seq": "INTEGER",
    "prev_hash": "TEXT",
    "entry_hash": "TEXT",
    "headers_sha256": "TEXT",
    "body_excerpt_sha256": "TEXT",
}

# Columns added by the v3 retention migration.
_V3_RETENTION_COLUMNS = {
    "pruned_at": "TEXT",
    "pruned_fields": "TEXT",
    "legal_hold": "INTEGER NOT NULL DEFAULT 0",
}

# Text columns retention clears, paired with the digest column that keeps the
# chain verifiable once the text is gone.
PRUNABLE_CONTENT = (("body_excerpt", "body_excerpt_sha256"), ("headers_json", "headers_sha256"))
# Cap stored request bodies at 100 KB. The proxy still forwards the full body;
# this only bounds what lands in the audit DB. ``body_hash`` covers the whole
# body for integrity, ``req_bytes`` records the true size. Bigger than the old
# 4 KB so large prompt/telemetry payloads are captured whole for the Article 26
# "what was sent" record, while still bounding DB growth.
BODY_EXCERPT_MAX = 100 * 1024


@dataclass(frozen=True)
class RequestRecord:
    """One row in the requests table.

    Fields filled in by later-day addons (``tool`` on Day 4, ``redactions_applied_json``
    on Day 7, ``enforcement`` on Day 8) are ``None`` by default so Day 3 capture
    can build a record without knowing about them.

    ``enforcement`` is the allowlist outcome: ``None`` (on-allowlist or no
    policy), ``"flagged"`` (off-allowlist, forwarded anyway), or ``"blocked"``
    (off-allowlist, short-circuited with a 403). Only ``"blocked"`` means the
    request never reached the cloud.
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
    enforcement: str | None


_INSERT_COLUMNS = (
    "ts, tool, method, scheme, host, path, req_bytes, resp_bytes, status, "
    "headers_json, body_excerpt, body_hash, redactions_applied_json, enforcement, "
    "seq, prev_hash, entry_hash, headers_sha256, body_excerpt_sha256"
)
_INSERT_PLACEHOLDERS = ", ".join("?" * 19)


class ReadOnlyStoreError(RuntimeError):
    """Raised when a write is attempted on a store opened read-only."""


@dataclass(frozen=True)
class PruneResult:
    """What a retention pass actually did."""

    bodies_cleared: int
    records_deleted: int
    gap_seq_start: int | None = None
    gap_seq_end: int | None = None


@dataclass(frozen=True)
class ChainVerification:
    """Outcome of verifying the hash chain.

    ``status`` is ``ok``, ``broken``, or ``empty``. ``unchained`` counts rows
    written before v0.2, which carry no ``seq`` and are outside the chain: they
    are not a failure, but an export must disclose them.
    """

    status: str
    checked: int
    unchained: int
    first_seq: int | None
    last_seq: int | None
    head_hash: str
    broken_at: int | None = None
    detail: str | None = None
    # Entries whose text columns were cleared by retention. Their digests are
    # still chained, so the chain verifies, but the content behind those
    # digests can no longer be checked and the count must be disclosed.
    content_unavailable: int = 0
    # Entries removed by a recorded retention deletion. Verification resumes
    # across those gaps, but an export must disclose them: the surviving chain
    # says nothing about what was in the deleted range.
    entries_deleted: int = 0


class Store:
    """SQLite audit-log store. Open is idempotent.

    Pass ``read_only=True`` for reader processes (the dashboard). The hash
    chain is only sound with a single writer, and a stray write from a second
    process produces a break indistinguishable from tampering.
    """

    def __init__(self, path: Path | None = None, *, read_only: bool = False) -> None:
        # Resolve at call time so tests can monkeypatch DEFAULT_DB_PATH.
        resolved = path if path is not None else DEFAULT_DB_PATH
        self.path = resolved
        self._read_only = read_only
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(resolved, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._migrate()
        self._enable_wal()
        # After WAL: enabling it creates the -wal and -shm files, which hold
        # recently written rows and need the same mode as the database.
        harden_path_permissions(resolved)
        if read_only:
            # Set last: schema init and migration both need to write.
            self._conn.execute("PRAGMA query_only = 1")

    def _init_schema(self) -> None:
        schema = resources.files("upbox.db").joinpath("schema.sql").read_text()
        self._conn.executescript(schema)

    def _migrate(self) -> None:
        """Bring an existing database to ``SCHEMA_VERSION``.

        A fresh database is already at the final shape, but reports version 0
        (no ``schema_version`` row) and runs every step. Each step is therefore
        guarded so it is a no-op when the schema is already correct.
        """
        version = self._schema_version()
        if version < 1:
            self._migrate_v1_enforcement()
        if version < 2:
            self._migrate_v2_chain()
        if version < 3:
            self._migrate_v3_retention()
        self._conn.execute(
            "INSERT INTO schema_version (id, version) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET version = excluded.version",
            (SCHEMA_VERSION,),
        )

    def _schema_version(self) -> int:
        row = self._conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
        return int(row[0]) if row is not None else 0

    def _request_columns(self) -> set[str]:
        return {row[1] for row in self._conn.execute("PRAGMA table_info(requests)")}

    def _migrate_v1_enforcement(self) -> None:
        # Databases created before the warn/block split have a boolean
        # ``blocked`` column but no ``enforcement``. ``CREATE TABLE IF NOT
        # EXISTS`` leaves them untouched, so add the column here or inserts
        # referencing ``enforcement`` would fail. Old ``blocked=1`` rows
        # conflated warn + block; backfill them to 'flagged' since the shipped
        # default only ever produced warns (forwarded), not real 403s.
        columns = self._request_columns()
        if "enforcement" in columns:
            return
        self._conn.execute("ALTER TABLE requests ADD COLUMN enforcement TEXT")
        if "blocked" in columns:
            self._conn.execute("UPDATE requests SET enforcement = 'flagged' WHERE blocked = 1")

    def _migrate_v2_chain(self) -> None:
        # Chain columns stay NULL on pre-v0.2 rows. Backfilling them would
        # produce a chain over rows that were freely editable before the chain
        # existed, which proves nothing and misleads anyone who verifies it.
        columns = self._request_columns()
        for name, affinity in _V2_CHAIN_COLUMNS.items():
            if name not in columns:
                self._conn.execute(f"ALTER TABLE requests ADD COLUMN {name} {affinity}")
        # Created here rather than in schema.sql: on a v0.1 database the seq
        # column does not exist when schema.sql runs. NULLs are exempt from
        # UNIQUE in SQLite, so unchained rows coexist fine.
        self._conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_seq ON requests(seq)")

    def _migrate_v3_retention(self) -> None:
        columns = self._request_columns()
        for name, definition in _V3_RETENTION_COLUMNS.items():
            if name not in columns:
                self._conn.execute(f"ALTER TABLE requests ADD COLUMN {name} {definition}")

    def _enable_wal(self) -> None:
        row = self._conn.execute("PRAGMA journal_mode=WAL").fetchone()
        # In-memory databases silently refuse WAL and return "memory". That's
        # fine for tests. Anything else that isn't WAL is a real problem.
        actual = row[0].lower()
        if actual not in {"wal", "memory"}:
            raise RuntimeError(f"failed to enable WAL mode (got {actual!r})")

    def insert_request(self, record: RequestRecord) -> int:
        """Append one request, linking it into the hash chain.

        The row insert and the chain-head advance are one transaction: a crash
        between them would otherwise leave the head pointing at an entry that
        is not in the log, which reads as tampering.
        """
        headers_sha256 = chain.hash_text(record.headers_json)
        body_excerpt_sha256 = chain.hash_text(record.body_excerpt)
        with self._write_transaction():
            seq, prev_hash = self._chain_head()
            entry_hash = chain.entry_hash(
                {
                    "seq": seq,
                    "ts": record.ts,
                    "tool": record.tool,
                    "method": record.method,
                    "scheme": record.scheme,
                    "host": record.host,
                    "path": record.path,
                    "req_bytes": record.req_bytes,
                    "resp_bytes": record.resp_bytes,
                    "status": record.status,
                    "headers_sha256": headers_sha256,
                    "body_hash": record.body_hash,
                    "body_excerpt_sha256": body_excerpt_sha256,
                    "redactions_applied_json": record.redactions_applied_json,
                    "enforcement": record.enforcement,
                    "prev_hash": prev_hash,
                }
            )
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
                    record.enforcement,
                    seq,
                    prev_hash,
                    entry_hash,
                    headers_sha256,
                    body_excerpt_sha256,
                ),
            )
            self._conn.execute(
                "UPDATE chain_state SET next_seq = ?, head_hash = ? WHERE id = 1",
                (seq + 1, entry_hash),
            )
        rowid = cursor.lastrowid
        if rowid is None:
            raise RuntimeError("insert returned no rowid")
        return rowid

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        if self._read_only:
            raise ReadOnlyStoreError(f"{self.path} is open read-only")
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def _chain_head(self) -> tuple[int, str]:
        """Return ``(next_seq, head_hash)``, seeding genesis on first use.

        Must be called inside ``_write_transaction``.
        """
        row = self._conn.execute(
            "SELECT next_seq, head_hash FROM chain_state WHERE id = 1"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO chain_state (id, next_seq, head_hash) VALUES (1, 1, ?)",
                (chain.GENESIS_PREV_HASH,),
            )
            return 1, chain.GENESIS_PREV_HASH
        return int(row["next_seq"]), str(row["head_hash"])

    def head_hash(self) -> str:
        """Current chain head, or the genesis value if nothing is chained yet."""
        row = self._conn.execute("SELECT head_hash FROM chain_state WHERE id = 1").fetchone()
        return str(row["head_hash"]) if row is not None else chain.GENESIS_PREV_HASH

    def write_checkpoint(self, reason: str) -> sqlite3.Row:
        """Seal the current head into ``chain_checkpoints`` and return the row.

        A checkpoint only proves anything once its ``head_hash`` has left the
        machine, so callers should surface the value rather than just storing
        it.
        """
        with self._write_transaction():
            next_seq, head = self._chain_head()
            cursor = self._conn.execute(
                "INSERT INTO chain_checkpoints (ts, seq_end, head_hash, entry_count, reason) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    datetime.now(UTC).isoformat(),
                    next_seq - 1,
                    head,
                    self._chained_row_count(),
                    reason,
                ),
            )
            checkpoint_id = cursor.lastrowid
        row = self._conn.execute(
            "SELECT * FROM chain_checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()
        return cast("sqlite3.Row", row)

    def prune(self, policy: RetentionPolicy, now: datetime | None = None) -> PruneResult:
        """Apply a retention policy. Returns what it did without printing.

        Bodies are cleared first, then whole rows are deleted, so a row that
        crosses both cutoffs in the same pass is not counted twice. Rows under
        ``legal_hold`` are exempt from both tiers.
        """
        moment = now if now is not None else datetime.now(UTC)
        stamp = moment.isoformat()

        bodies_cleared = 0
        records_deleted = 0
        gap: sqlite3.Row | None = None

        body_cutoff = policy.body_cutoff(moment)
        record_cutoff = policy.record_cutoff(moment)

        with self._write_transaction():
            if body_cutoff is not None:
                cleared_columns = json.dumps([text for text, _ in PRUNABLE_CONTENT])
                cursor = self._conn.execute(
                    "UPDATE requests SET body_excerpt = NULL, headers_json = NULL, "
                    "pruned_at = ?, pruned_fields = ? "
                    "WHERE ts < ? AND legal_hold = 0 AND pruned_at IS NULL",
                    (stamp, cleared_columns, body_cutoff.isoformat()),
                )
                bodies_cleared = cursor.rowcount

            if record_cutoff is not None:
                gap = self._delete_records_before(record_cutoff, stamp)
                records_deleted = int(gap["entry_count"]) if gap is not None else 0

        return PruneResult(
            bodies_cleared=bodies_cleared,
            records_deleted=records_deleted,
            gap_seq_start=int(gap["seq_start"]) if gap is not None else None,
            gap_seq_end=int(gap["seq_end"]) if gap is not None else None,
        )

    def _delete_records_before(self, cutoff: datetime, stamp: str) -> sqlite3.Row | None:
        """Delete chained rows older than ``cutoff`` and record the gap.

        Only a contiguous run from the oldest surviving entry is deletable. A
        legal hold in the middle of the range stops the run there rather than
        punching a second hole, because each hole needs its own gap record and
        a hold is a signal to stop pruning, not to prune around.
        """
        candidates = list(
            self._conn.execute(
                "SELECT seq, entry_hash, legal_hold, ts FROM requests "
                "WHERE seq IS NOT NULL ORDER BY seq"
            )
        )
        deletable: list[sqlite3.Row] = []
        for row in candidates:
            if row["legal_hold"] or row["ts"] >= cutoff.isoformat():
                break
            deletable.append(row)
        if not deletable:
            return None

        seq_start = int(deletable[0]["seq"])
        seq_end = int(deletable[-1]["seq"])
        self._conn.execute("DELETE FROM requests WHERE seq BETWEEN ? AND ?", (seq_start, seq_end))
        cursor = self._conn.execute(
            "INSERT INTO chain_gaps (ts, seq_start, seq_end, entry_count, last_entry_hash, reason) "
            "VALUES (?, ?, ?, ?, ?, 'retention')",
            (stamp, seq_start, seq_end, len(deletable), str(deletable[-1]["entry_hash"])),
        )
        row = self._conn.execute(
            "SELECT * FROM chain_gaps WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return cast("sqlite3.Row | None", row)

    def set_legal_hold(
        self, since: str | None = None, until: str | None = None, *, held: bool = True
    ) -> int:
        """Exempt a timestamp range from retention. Returns rows affected."""
        clauses: list[str] = []
        params: list[Any] = [1 if held else 0]
        if since:
            clauses.append("ts >= ?")
            params.append(since)
        if until:
            clauses.append("ts <= ?")
            params.append(until)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._write_transaction():
            cursor = self._conn.execute(
                f"UPDATE requests SET legal_hold = ? {where}", tuple(params)
            )
        return cursor.rowcount

    def _gaps_by_start(self) -> dict[int, sqlite3.Row]:
        return {
            int(row["seq_start"]): row
            for row in self._conn.execute("SELECT * FROM chain_gaps ORDER BY seq_start")
        }

    def _chained_row_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM requests WHERE seq IS NOT NULL").fetchone()
        return int(row[0])

    def verify_chain(self) -> ChainVerification:
        """Recompute every chained entry and check its linkage.

        Detects edited content, deleted rows (seq gaps), inserted or reordered
        rows (linkage breaks), and a stored head that disagrees with the log.
        Stops at the first break, since everything after it is unverifiable.
        """
        unchained = int(
            self._conn.execute("SELECT COUNT(*) FROM requests WHERE seq IS NULL").fetchone()[0]
        )
        rows = self._conn.execute("SELECT * FROM requests WHERE seq IS NOT NULL ORDER BY seq")

        gaps = self._gaps_by_start()
        expected_prev = chain.GENESIS_PREV_HASH
        expected_seq = 1
        checked = 0
        content_unavailable = 0
        entries_deleted = 0
        first_seq: int | None = None
        last_seq: int | None = None

        def broken(seq: int, detail: str) -> ChainVerification:
            return ChainVerification(
                status="broken",
                checked=checked,
                unchained=unchained,
                first_seq=first_seq,
                last_seq=last_seq,
                head_hash=self.head_hash(),
                broken_at=seq,
                detail=detail,
                content_unavailable=content_unavailable,
                entries_deleted=entries_deleted,
            )

        for row in rows:
            seq = int(row["seq"])
            if first_seq is None:
                first_seq = seq
            # A gap is only acceptable where a retention deletion recorded both
            # its range and the hash of the last entry it removed, which is what
            # lets linkage resume. An unrecorded gap is tampering.
            # A while loop, not an if: successive retention passes leave
            # adjacent gaps (1-2, then 3-4), and each has to be consumed in
            # turn or the second one reads as tampering. Terminates because
            # seq_end >= seq_start, so expected_seq strictly increases.
            while seq != expected_seq and expected_seq in gaps:
                gap = gaps[expected_seq]
                expected_prev = str(gap["last_entry_hash"])
                entries_deleted += int(gap["entry_count"])
                expected_seq = int(gap["seq_end"]) + 1
            if seq != expected_seq:
                return broken(seq, f"sequence gap: expected seq {expected_seq}, found {seq}")
            if row["prev_hash"] != expected_prev:
                return broken(seq, f"seq {seq} does not link to the previous entry")
            recomputed = chain.entry_hash(chain.chain_payload(_row_to_dict(row)))
            if recomputed != row["entry_hash"]:
                return broken(seq, f"seq {seq} does not match its recorded hash")

            # The chain commits to the digests, so a digest column that no
            # longer describes its text column would otherwise slip through:
            # an attacker could rewrite a prompt body and leave the hash alone.
            # A null text column is retention having cleared it, which is
            # legitimate but leaves the content uncheckable.
            for text_column, digest_column in (
                ("body_excerpt", "body_excerpt_sha256"),
                ("headers_json", "headers_sha256"),
            ):
                if row[text_column] is None:
                    if row[digest_column] is not None:
                        content_unavailable += 1
                    continue
                if chain.hash_text(row[text_column]) != row[digest_column]:
                    return broken(seq, f"seq {seq} {text_column} does not match its stored digest")

            expected_prev = str(row["entry_hash"])
            expected_seq = seq + 1
            last_seq = seq
            checked += 1

        if checked == 0:
            return ChainVerification(
                status="empty",
                checked=0,
                unchained=unchained,
                first_seq=None,
                last_seq=None,
                head_hash=self.head_hash(),
            )

        stored_head = self.head_hash()
        if stored_head != expected_prev:
            assert last_seq is not None
            return broken(
                last_seq,
                "stored chain head does not match the end of the log (entries removed?)",
            )

        return ChainVerification(
            status="ok",
            checked=checked,
            unchained=unchained,
            first_seq=first_seq,
            last_seq=last_seq,
            head_hash=stored_head,
            content_unavailable=content_unavailable,
            entries_deleted=entries_deleted,
        )

    def query_recent(self, limit: int = 100) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM requests ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        )

    def query_by_id(self, request_id: int) -> sqlite3.Row | None:
        row = self._conn.execute(
            "SELECT * FROM requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        return cast("sqlite3.Row | None", row)

    def query_filtered(
        self,
        since: str | None = None,
        until: str | None = None,
        tool: str | None = None,
        status: str | None = None,
        search: str | None = None,
        order: str = "ASC",
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        """Filtered query. All filters are AND-combined.

        ``status`` is one of ``forwarded``/``redacted``/``flagged``/``blocked``
        and shapes the badge on each row. ``flagged`` and ``blocked`` are
        distinct: flagged requests were forwarded to the cloud (off-allowlist
        under a warn policy), blocked ones were stopped with a 403.
        ``forwarded`` means sent cleanly — on-allowlist and unredacted.
        ``search`` matches against host, path, and tool with case-insensitive
        LIKE — callers escape ``%`` / ``_`` themselves or accept that those
        become wildcards.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if since:
            clauses.append("ts >= ?")
            params.append(since)
        if until:
            clauses.append("ts <= ?")
            params.append(until)
        if tool:
            clauses.append("tool = ?")
            params.append(tool)
        if status == "blocked":
            clauses.append("enforcement = 'blocked'")
        elif status == "flagged":
            clauses.append("enforcement = 'flagged'")
        elif status == "redacted":
            clauses.append("redactions_applied_json IS NOT NULL")
        elif status == "forwarded":
            clauses.append("enforcement IS NULL AND redactions_applied_json IS NULL")
        if search:
            pattern = f"%{search}%"
            clauses.append(
                "(LOWER(host) LIKE LOWER(?)"
                " OR LOWER(path) LIKE LOWER(?)"
                " OR LOWER(COALESCE(tool, '')) LIKE LOWER(?))"
            )
            params.extend([pattern, pattern, pattern])
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        order_clause = "DESC" if order.upper() == "DESC" else "ASC"
        limit_clause = f" LIMIT {int(limit)}" if limit else ""
        return list(
            self._conn.execute(
                f"SELECT * FROM requests {where} ORDER BY id {order_clause}{limit_clause}",
                tuple(params),
            )
        )

    def dashboard_stats(self) -> sqlite3.Row:
        """Aggregate counts for the stats bar.

        ``flagged`` (off-allowlist, forwarded) and ``blocked`` (off-allowlist,
        stopped with 403) are counted separately — conflating them would let
        the tile claim a request was stopped when it actually reached the cloud.
        """
        row = self._conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN redactions_applied_json IS NOT NULL THEN 1 ELSE 0 END) AS redacted,
                SUM(CASE WHEN enforcement = 'flagged' THEN 1 ELSE 0 END) AS flagged,
                SUM(CASE WHEN enforcement = 'blocked' THEN 1 ELSE 0 END) AS blocked,
                COALESCE(SUM(req_bytes), 0) AS total_bytes
            FROM requests
            """
        ).fetchone()
        return cast("sqlite3.Row", row)

    def per_tool_summary(self) -> list[sqlite3.Row]:
        """Per-tool aggregates for the dashboard tiles."""
        return list(
            self._conn.execute(
                """
                SELECT
                    COALESCE(tool, 'Unknown') AS tool,
                    COUNT(*)                  AS request_count,
                    COALESCE(SUM(req_bytes), 0) AS total_req_bytes,
                    SUM(CASE WHEN enforcement = 'blocked' THEN 1 ELSE 0 END) AS blocked_count
                FROM requests
                GROUP BY tool
                ORDER BY request_count DESC
                """
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


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Materialise a row as a name-keyed dict.

    ``dict(row)`` does not work: ``sqlite3.Row`` iterates over values, not
    keys, so the ``.keys()`` call is load-bearing rather than redundant.
    """
    return {key: row[key] for key in row.keys()}  # noqa: SIM118


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
