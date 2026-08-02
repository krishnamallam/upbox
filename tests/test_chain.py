"""Tests for the tamper-evident hash chain.

The canonical-bytes test is the important one: it pins the exact serialisation
every stored hash was computed from. If a refactor changes those bytes, every
historical entry_hash silently stops verifying, and the failure would otherwise
only surface on a user's database.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from upbox.db import chain
from upbox.db.store import ReadOnlyStoreError, RequestRecord, Store


@pytest.fixture
def tmp_store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


def _make_record(**overrides: object) -> RequestRecord:
    base: dict[str, object] = {
        "ts": "2026-08-02T09:00:00+00:00",
        "tool": "cursor",
        "method": "POST",
        "scheme": "https",
        "host": "api.anthropic.com",
        "path": "/v1/messages",
        "req_bytes": 42,
        "resp_bytes": 100,
        "status": 200,
        "headers_json": '{"content-type": "application/json"}',
        "body_excerpt": '{"prompt": "hi"}',
        "body_hash": "deadbeef",
        "redactions_applied_json": None,
        "enforcement": None,
    }
    base.update(overrides)
    return RequestRecord(**base)  # type: ignore[arg-type]


# --- canonicalisation ------------------------------------------------------


def test_canonical_json_sorts_keys_and_strips_whitespace() -> None:
    payload = {"b": 1, "a": "x"}

    assert chain.canonical_json(payload) == b'{"a":"x","b":1}'


def test_canonical_json_is_stable_across_key_insertion_order() -> None:
    first = chain.canonical_json({"a": 1, "b": 2})
    second = chain.canonical_json({"b": 2, "a": 1})

    assert first == second


def test_canonical_json_keeps_non_ascii_unescaped() -> None:
    assert chain.canonical_json({"path": "/caffè"}) == '{"path":"/caffè"}'.encode()


def test_canonical_json_rejects_floats() -> None:
    with pytest.raises(TypeError, match="float"):
        chain.canonical_json({"req_bytes": 1.5})


def test_canonical_json_rejects_unchainable_types() -> None:
    with pytest.raises(TypeError, match="unchainable"):
        chain.canonical_json({"tool": ["a"]})


def test_entry_hash_is_pinned_for_a_fixed_payload() -> None:
    """Golden hash. Changing it invalidates every stored entry_hash."""
    payload = dict.fromkeys(chain.CHAINED_FIELDS)
    payload.update({"seq": 1, "prev_hash": chain.GENESIS_PREV_HASH, "host": "api.example.com"})

    assert (
        chain.entry_hash(payload)
        == "6b628f1f846b30bcd0cafd9dc63b984fcd680dab7511ba3b609dd76adc4ffa1c"
    )


def test_entry_hash_is_domain_separated_from_a_plain_digest() -> None:
    payload = {"seq": 1}

    import hashlib

    plain = hashlib.sha256(chain.canonical_json(payload)).hexdigest()

    assert chain.entry_hash(payload) != plain


def test_hash_text_returns_none_for_null_columns() -> None:
    assert chain.hash_text(None) is None


# --- chaining on insert ----------------------------------------------------


def test_first_insert_links_to_genesis(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record())

    assert tmp_store.query_recent()[0]["prev_hash"] == chain.GENESIS_PREV_HASH


def test_seq_starts_at_one(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record())

    assert tmp_store.query_recent()[0]["seq"] == 1


def test_seq_increments_per_insert(tmp_store: Store) -> None:
    for _ in range(3):
        tmp_store.insert_request(_make_record())

    assert [row["seq"] for row in tmp_store.query_filtered()] == [1, 2, 3]


def test_each_entry_links_to_its_predecessor(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record())
    tmp_store.insert_request(_make_record())
    first, second = tmp_store.query_filtered()

    assert second["prev_hash"] == first["entry_hash"]


def test_head_hash_tracks_the_last_entry(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record())
    tmp_store.insert_request(_make_record())

    assert tmp_store.head_hash() == tmp_store.query_filtered()[-1]["entry_hash"]


def test_chain_commits_to_the_headers_digest_not_the_text(tmp_store: Store) -> None:
    headers = '{"content-type": "application/json"}'
    tmp_store.insert_request(_make_record(headers_json=headers))

    assert tmp_store.query_recent()[0]["headers_sha256"] == chain.hash_text(headers)


def test_identical_records_get_different_hashes(tmp_store: Store) -> None:
    """seq and prev_hash are inside the payload, so duplicates never collide."""
    tmp_store.insert_request(_make_record())
    tmp_store.insert_request(_make_record())
    first, second = tmp_store.query_filtered()

    assert first["entry_hash"] != second["entry_hash"]


# --- verification ----------------------------------------------------------


def test_verify_reports_empty_on_a_fresh_database(tmp_store: Store) -> None:
    assert tmp_store.verify_chain().status == "empty"


def test_verify_passes_on_an_untouched_chain(tmp_store: Store) -> None:
    for _ in range(5):
        tmp_store.insert_request(_make_record())

    assert tmp_store.verify_chain().status == "ok"


def test_verify_counts_every_entry(tmp_store: Store) -> None:
    for _ in range(5):
        tmp_store.insert_request(_make_record())

    assert tmp_store.verify_chain().checked == 5


def test_verify_detects_an_edited_host(tmp_store: Store) -> None:
    for _ in range(3):
        tmp_store.insert_request(_make_record())
    tmp_store._conn.execute("UPDATE requests SET host = 'evil.example.com' WHERE seq = 2")

    assert tmp_store.verify_chain().status == "broken"


def test_verify_points_at_the_edited_entry(tmp_store: Store) -> None:
    for _ in range(3):
        tmp_store.insert_request(_make_record())
    tmp_store._conn.execute("UPDATE requests SET host = 'evil.example.com' WHERE seq = 2")

    assert tmp_store.verify_chain().broken_at == 2


def test_verify_detects_an_edited_body_excerpt(tmp_store: Store) -> None:
    """Bodies are chained via their digest, so editing the text still breaks it."""
    tmp_store.insert_request(_make_record())
    tmp_store._conn.execute("UPDATE requests SET body_excerpt = 'tampered' WHERE seq = 1")

    assert tmp_store.verify_chain().status == "broken"


def test_verify_detects_a_deleted_row(tmp_store: Store) -> None:
    for _ in range(3):
        tmp_store.insert_request(_make_record())
    tmp_store._conn.execute("DELETE FROM requests WHERE seq = 2")

    assert tmp_store.verify_chain().status == "broken"


def test_verify_detects_tail_truncation_against_the_stored_head(tmp_store: Store) -> None:
    for _ in range(3):
        tmp_store.insert_request(_make_record())
    tmp_store._conn.execute("DELETE FROM requests WHERE seq = 3")

    assert tmp_store.verify_chain().status == "broken"


def test_verify_ignores_rows_that_predate_the_chain(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record())
    tmp_store._conn.execute(
        "INSERT INTO requests (ts, host, method) "
        "VALUES ('2026-01-01T00:00:00', 'old.example', 'GET')"
    )

    assert tmp_store.verify_chain().status == "ok"


def test_verify_counts_rows_that_predate_the_chain(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record())
    tmp_store._conn.execute(
        "INSERT INTO requests (ts, host, method) "
        "VALUES ('2026-01-01T00:00:00', 'old.example', 'GET')"
    )

    assert tmp_store.verify_chain().unchained == 1


# --- checkpoints -----------------------------------------------------------


def test_checkpoint_records_the_current_head(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record())

    assert tmp_store.write_checkpoint("manual")["head_hash"] == tmp_store.head_hash()


def test_checkpoint_records_the_last_sealed_seq(tmp_store: Store) -> None:
    for _ in range(4):
        tmp_store.insert_request(_make_record())

    assert tmp_store.write_checkpoint("manual")["seq_end"] == 4


# --- single-writer discipline ----------------------------------------------


def test_read_only_store_refuses_to_insert(tmp_path: Path) -> None:
    Store(tmp_path / "ro.db").close()
    reader = Store(tmp_path / "ro.db", read_only=True)

    with pytest.raises(ReadOnlyStoreError):
        reader.insert_request(_make_record())


def test_read_only_store_still_reads(tmp_path: Path) -> None:
    writer = Store(tmp_path / "ro.db")
    writer.insert_request(_make_record())
    writer.close()

    assert len(Store(tmp_path / "ro.db", read_only=True).query_recent()) == 1


# --- migration -------------------------------------------------------------


def test_v01_database_gains_the_chain_columns(tmp_path: Path) -> None:
    """A v0.1 database opened by v0.2 must migrate, not crash."""
    import sqlite3

    path = tmp_path / "old.db"
    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE requests (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, tool TEXT, "
        "method TEXT, scheme TEXT, host TEXT, path TEXT, req_bytes INTEGER, "
        "resp_bytes INTEGER, status INTEGER, headers_json TEXT, body_excerpt TEXT, "
        "body_hash TEXT, redactions_applied_json TEXT, blocked INTEGER)"
    )
    legacy.execute("INSERT INTO requests (ts, host, blocked) VALUES ('2026-01-01', 'a.example', 1)")
    legacy.commit()
    legacy.close()

    store = Store(path)
    columns = {row[1] for row in store._conn.execute("PRAGMA table_info(requests)")}

    assert {"seq", "prev_hash", "entry_hash", "headers_sha256"} <= columns


def test_migrated_database_can_be_appended_to(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "old.db"
    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE requests (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, tool TEXT, "
        "method TEXT, scheme TEXT, host TEXT, path TEXT, req_bytes INTEGER, "
        "resp_bytes INTEGER, status INTEGER, headers_json TEXT, body_excerpt TEXT, "
        "body_hash TEXT, redactions_applied_json TEXT, blocked INTEGER)"
    )
    legacy.execute("INSERT INTO requests (ts, host) VALUES ('2026-01-01', 'a.example')")
    legacy.commit()
    legacy.close()

    store = Store(path)
    store.insert_request(_make_record())

    assert store.verify_chain().status == "ok"


def test_fresh_and_migrated_schemas_match(tmp_path: Path) -> None:
    import sqlite3

    legacy_path = tmp_path / "old.db"
    legacy = sqlite3.connect(legacy_path)
    legacy.execute(
        "CREATE TABLE requests (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, tool TEXT, "
        "method TEXT, scheme TEXT, host TEXT, path TEXT, req_bytes INTEGER, "
        "resp_bytes INTEGER, status INTEGER, headers_json TEXT, body_excerpt TEXT, "
        "body_hash TEXT, redactions_applied_json TEXT, blocked INTEGER)"
    )
    legacy.commit()
    legacy.close()

    migrated = {row[1] for row in Store(legacy_path)._conn.execute("PRAGMA table_info(requests)")}
    fresh = {
        row[1] for row in Store(tmp_path / "new.db")._conn.execute("PRAGMA table_info(requests)")
    }

    assert fresh <= migrated


def test_body_excerpt_digest_survives_the_text_being_cleared(tmp_store: Store) -> None:
    """The property retention depends on: null the text, chain still verifies."""
    tmp_store.insert_request(_make_record())
    tmp_store._conn.execute("UPDATE requests SET body_excerpt = NULL, headers_json = NULL")

    assert tmp_store.verify_chain().status == "ok"


def test_cleared_text_is_reported_as_content_unavailable(tmp_store: Store) -> None:
    """Verifying must not silently pass off uncheckable content as verified."""
    tmp_store.insert_request(_make_record())
    tmp_store._conn.execute("UPDATE requests SET body_excerpt = NULL, headers_json = NULL")

    assert tmp_store.verify_chain().content_unavailable == 2


def test_verify_detects_an_edited_headers_column(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record())
    tmp_store._conn.execute("""UPDATE requests SET headers_json = '{"x": "y"}' WHERE seq = 1""")

    assert tmp_store.verify_chain().status == "broken"


def test_verify_rejects_a_body_edited_with_its_digest_left_intact(tmp_store: Store) -> None:
    """The chain commits to the digest, so the text must be checked against it.

    Without this check an attacker could rewrite a prompt body, leave
    body_excerpt_sha256 alone, and have the chain verify clean.
    """
    tmp_store.insert_request(_make_record())
    tmp_store._conn.execute("UPDATE requests SET body_excerpt = 'rewritten' WHERE seq = 1")

    assert tmp_store.verify_chain().status == "broken"


def test_untouched_chain_reports_no_unavailable_content(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record())

    assert tmp_store.verify_chain().content_unavailable == 0


def test_redactions_column_is_chained(tmp_store: Store) -> None:
    tmp_store.insert_request(_make_record(redactions_applied_json=json.dumps(["openai-key"])))
    tmp_store._conn.execute("UPDATE requests SET redactions_applied_json = '[]' WHERE seq = 1")

    assert tmp_store.verify_chain().status == "broken"
