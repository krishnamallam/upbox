-- upbox audit log schema.
--
-- One row per AI tool request seen by the proxy. The WAL pragma is set at
-- runtime by Store after open so concurrent reads (dashboard) and the
-- single writer (proxy) coexist without locking each other out.

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
    enforcement              TEXT
);

CREATE INDEX IF NOT EXISTS idx_requests_ts   ON requests(ts);
CREATE INDEX IF NOT EXISTS idx_requests_tool ON requests(tool);
CREATE INDEX IF NOT EXISTS idx_requests_host ON requests(host);
