-- upbox audit log schema.
--
-- One row per AI tool request seen by the proxy. The WAL pragma is set at
-- runtime by Store after open so concurrent reads (dashboard) and the
-- single writer (proxy) coexist without locking each other out.
--
-- This file describes a *fresh* database. Existing databases are brought
-- forward by the numbered migrations in Store._migrate, keyed on the
-- schema_version table. Both paths must end at the same shape, and a test
-- asserts they do.

CREATE TABLE IF NOT EXISTS requests (
    id                       INTEGER PRIMARY KEY,
    ts                       TEXT    NOT NULL,
    tool                     TEXT,
    method                   TEXT,
    scheme                   TEXT,
    host                     TEXT,
    path                     TEXT,
    req_bytes                INTEGER,
    resp_bytes               INTEGER,
    status                   INTEGER,
    headers_json             TEXT,
    body_excerpt             TEXT,
    body_hash                TEXT,
    redactions_applied_json  TEXT,
    -- Enforcement outcome: NULL = on-allowlist (or no policy), 'flagged' =
    -- off-allowlist but still FORWARDED (block_unknown: warn), 'blocked' =
    -- off-allowlist and short-circuited with a 403 (block_unknown: block).
    -- 'flagged' requests reached the cloud; only 'blocked' ones did not.
    enforcement              TEXT,

    -- Hash chain. seq is the chain position and is NULL for rows written
    -- before v0.2: they sit outside the chain and are never backfilled, since
    -- a chain computed today over rows that were editable yesterday proves
    -- nothing.
    seq                      INTEGER,
    prev_hash                TEXT,
    entry_hash               TEXT,
    -- The chain commits to these digests rather than to the text columns, so
    -- retention can null out headers_json/body_excerpt and the chain still
    -- verifies.
    headers_sha256           TEXT,
    body_excerpt_sha256      TEXT
);

CREATE INDEX IF NOT EXISTS idx_requests_ts   ON requests(ts);
CREATE INDEX IF NOT EXISTS idx_requests_tool ON requests(tool);
CREATE INDEX IF NOT EXISTS idx_requests_host ON requests(host);
-- idx_requests_seq is created by the v2 migration, not here: on a v0.1
-- database this file runs before the seq column exists.

CREATE TABLE IF NOT EXISTS schema_version (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);

-- Single-row chain head, so appending never has to scan the log.
CREATE TABLE IF NOT EXISTS chain_state (
    id        INTEGER PRIMARY KEY CHECK (id = 1),
    next_seq  INTEGER NOT NULL,
    head_hash TEXT    NOT NULL
);

-- Sealed points in the chain. This is what a user prints, mails to counsel,
-- commits to a repo, or takes to a timestamping authority. A checkpoint whose
-- head_hash escaped the machine is the only thing that makes tail truncation
-- detectable.
CREATE TABLE IF NOT EXISTS chain_checkpoints (
    id          INTEGER PRIMARY KEY,
    ts          TEXT    NOT NULL,
    seq_end     INTEGER NOT NULL,
    head_hash   TEXT    NOT NULL,
    entry_count INTEGER NOT NULL,
    reason      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_seq_end ON chain_checkpoints(seq_end);
