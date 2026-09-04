"""Shared pytest fixtures for upbox tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# The requests table exactly as v0.2.0 shipped it (schema version 3): no
# omitted_fields, erased_at, or erased_reason. Built by hand rather than by
# dropping columns from a fresh database, because ALTER TABLE ... DROP COLUMN
# on a table whose definition carries inline comments fails on the SQLite
# builds some CI runners ship.
_V3_SCHEMA = """
CREATE TABLE requests (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, tool TEXT, method TEXT, scheme TEXT,
    host TEXT, path TEXT, req_bytes INTEGER, resp_bytes INTEGER, status INTEGER,
    headers_json TEXT, body_excerpt TEXT, body_hash TEXT, redactions_applied_json TEXT,
    enforcement TEXT, seq INTEGER, prev_hash TEXT, entry_hash TEXT, headers_sha256 TEXT,
    body_excerpt_sha256 TEXT, pruned_at TEXT, pruned_fields TEXT,
    legal_hold INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX idx_requests_seq ON requests(seq);
CREATE TABLE schema_version (id INTEGER PRIMARY KEY CHECK (id = 1), version INTEGER NOT NULL);
INSERT INTO schema_version (id, version) VALUES (1, 3);
"""


@pytest.fixture
def v3_db(tmp_path: Path) -> Path:
    """An empty database at schema version 3, the shape v0.2.0 left behind."""
    path = tmp_path / "v3.db"
    conn = sqlite3.connect(path)
    conn.executescript(_V3_SCHEMA)
    conn.close()
    return path
