"""Tests for the upbox.audit.v1 export format.

The disclosures are the point of this format, so most of these assert that the
file tells the truth about itself: what the chain check found, what retention
removed, what upbox cannot see, and what these records legally are not.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from upbox.audit_export import SCHEMA, write_audit_v1
from upbox.db.store import RequestRecord, Store
from upbox.retention import RetentionPolicy

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


@pytest.fixture
def tmp_store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


def _record(ts: datetime = NOW, **overrides: object) -> RequestRecord:
    base: dict[str, object] = {
        "ts": ts.isoformat(),
        "tool": "cursor",
        "method": "POST",
        "scheme": "https",
        "host": "api.anthropic.com",
        "path": "/v1/messages",
        "req_bytes": 16,
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


def _export(store: Store, **kwargs: Any) -> list[dict[str, Any]]:
    sink = io.StringIO()
    write_audit_v1(store, sink, **kwargs)
    return [json.loads(line) for line in sink.getvalue().splitlines()]


def _header(store: Store, **kwargs: Any) -> dict[str, Any]:
    return _export(store, **kwargs)[0]


# --- envelope --------------------------------------------------------------


def test_export_starts_with_a_header(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())

    assert _export(tmp_store)[0]["type"] == "upbox.audit.header"


def test_export_ends_with_a_footer(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())

    assert _export(tmp_store)[-1]["type"] == "upbox.audit.footer"


def test_export_names_its_schema(tmp_store: Store) -> None:
    assert _header(tmp_store)["schema"] == SCHEMA


def test_export_emits_one_record_per_row(tmp_store: Store) -> None:
    for _ in range(3):
        tmp_store.insert_request(_record())
    lines = _export(tmp_store)

    assert sum(1 for line in lines if line["type"] == "upbox.audit.record") == 3


def test_empty_log_still_produces_a_valid_envelope(tmp_store: Store) -> None:
    assert len(_export(tmp_store)) == 2


def test_returned_count_matches_the_records_written(tmp_store: Store) -> None:
    for _ in range(4):
        tmp_store.insert_request(_record())
    sink = io.StringIO()

    assert write_audit_v1(tmp_store, sink) == 4


def test_every_line_is_standalone_json(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())
    sink = io.StringIO()
    write_audit_v1(tmp_store, sink)

    assert all(json.loads(line) for line in sink.getvalue().splitlines())


# --- disclosures -----------------------------------------------------------


def test_header_states_the_chain_verified(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())

    assert _header(tmp_store)["chain"]["verification"] == "ok"


def test_header_reports_a_broken_chain_rather_than_hiding_it(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())
    tmp_store._conn.execute("UPDATE requests SET host = 'evil.example' WHERE seq = 1")

    assert _header(tmp_store)["chain"]["verification"] == "broken"


def test_header_carries_the_chain_head(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())

    assert _header(tmp_store)["chain"]["head_hash"] == tmp_store.head_hash()


def test_header_discloses_retention_deletions(tmp_store: Store) -> None:
    tmp_store.insert_request(_record(NOW - timedelta(days=500)))
    tmp_store.insert_request(_record(NOW))
    tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    assert _header(tmp_store)["chain"]["entries_deleted_by_retention"] == 1


def test_header_discloses_cleared_bodies(tmp_store: Store) -> None:
    tmp_store.insert_request(_record(NOW - timedelta(days=30)))
    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert _header(tmp_store)["chain"]["content_cleared_by_retention"] == 2


def test_header_discloses_rows_predating_the_chain(tmp_store: Store) -> None:
    tmp_store._conn.execute(
        "INSERT INTO requests (ts, host, method) "
        "VALUES ('2026-01-01T00:00:00', 'old.example', 'GET')"
    )

    assert _header(tmp_store)["chain"]["rows_predating_the_chain"] == 1


def test_header_carries_a_coverage_statement(tmp_store: Store) -> None:
    """An audit file that omits traffic silently reads as exhaustive."""
    assert "Absence of a record is not evidence" in _header(tmp_store)["coverage"]


def test_header_denies_being_article_26_logs(tmp_store: Store) -> None:
    assert "NOT the logs" in _header(tmp_store)["disclaimer"]


def test_header_records_the_ruleset_digests(tmp_store: Store) -> None:
    """Without these, 'which redaction rules were live' has no answer."""
    assert len(_header(tmp_store)["ruleset"]["redact_sha256"]) == 64


def test_header_notes_that_timestamps_are_unattested(tmp_store: Store) -> None:
    assert "Not attested" in _header(tmp_store)["field_notes"]["ts"]


def test_header_notes_body_hash_covers_the_redacted_body(tmp_store: Store) -> None:
    assert "after redaction" in _header(tmp_store)["field_notes"]["body_hash"]


# --- records ---------------------------------------------------------------


def test_record_carries_its_chain_position(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())

    assert _export(tmp_store)[1]["seq"] == 1


def test_record_carries_its_entry_hash(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())

    assert _export(tmp_store)[1]["chain"]["entry_hash"] == tmp_store.head_hash()


def test_flagged_records_say_they_reached_the_cloud(tmp_store: Store) -> None:
    """The single most misreadable field in the schema."""
    tmp_store.insert_request(_record(enforcement="flagged"))

    assert "forwarded" in _export(tmp_store)[1]["enforcement_meaning"]


def test_blocked_records_say_they_did_not(tmp_store: Store) -> None:
    tmp_store.insert_request(_record(enforcement="blocked"))

    assert "did not reach" in _export(tmp_store)[1]["enforcement_meaning"]


def test_untruncated_body_is_marked_as_such(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())

    assert _export(tmp_store)[1]["body_truncated"] is False


def test_truncated_body_is_marked_as_such(tmp_store: Store) -> None:
    tmp_store.insert_request(_record(req_bytes=999_999))

    assert _export(tmp_store)[1]["body_truncated"] is True


def test_redactions_are_emitted_as_a_list_not_a_json_string(tmp_store: Store) -> None:
    tmp_store.insert_request(_record(redactions_applied_json=json.dumps(["openai-key"])))

    assert _export(tmp_store)[1]["redactions"] == ["openai-key"]


def test_record_reports_its_retention_state(tmp_store: Store) -> None:
    tmp_store.insert_request(_record(NOW - timedelta(days=30)))
    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert _export(tmp_store)[1]["retention"]["pruned_fields"] == [
        "body_excerpt",
        "headers_json",
    ]


def test_record_reports_a_legal_hold(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())
    tmp_store.set_legal_hold()

    assert _export(tmp_store)[1]["retention"]["legal_hold"] is True


# --- filtering -------------------------------------------------------------


def test_tool_filter_narrows_the_records(tmp_store: Store) -> None:
    tmp_store.insert_request(_record(tool="cursor"))
    tmp_store.insert_request(_record(tool="copilot"))
    lines = _export(tmp_store, tool="cursor")

    assert sum(1 for line in lines if line["type"] == "upbox.audit.record") == 1


def test_header_echoes_the_filter_applied(tmp_store: Store) -> None:
    assert _header(tmp_store, tool="cursor")["filters"]["tool"] == "cursor"


def test_header_echoes_the_range_applied(tmp_store: Store) -> None:
    assert _header(tmp_store, since="2026-07-01")["range"]["since"] == "2026-07-01"


def test_record_count_reflects_the_filter(tmp_store: Store) -> None:
    tmp_store.insert_request(_record(tool="cursor"))
    tmp_store.insert_request(_record(tool="copilot"))

    assert _header(tmp_store, tool="cursor")["record_count"] == 1


# --- capture policy and erasure disclosures ---------------------------------


def test_header_records_the_capture_policy_digest(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())

    assert len(_header(tmp_store)["ruleset"]["capture_sha256"]) == 64


def test_header_counts_rows_with_omitted_content(tmp_store: Store) -> None:
    tmp_store.insert_request(
        _record(
            body_excerpt=None, headers_json=None, omitted_fields='["body_excerpt", "headers_json"]'
        )
    )

    assert _header(tmp_store)["chain"]["content_omitted_by_capture_policy"] == 1


def test_omitted_body_is_not_reported_as_untruncated(tmp_store: Store) -> None:
    tmp_store.insert_request(_record(body_excerpt=None, omitted_fields='["body_excerpt"]'))

    assert _export(tmp_store)[1]["body_truncated"] is None


def test_record_carries_the_omitted_fields(tmp_store: Store) -> None:
    tmp_store.insert_request(_record(body_excerpt=None, omitted_fields='["body_excerpt"]'))

    assert _export(tmp_store)[1]["capture"]["omitted_fields"] == ["body_excerpt"]


def test_full_record_reports_nothing_omitted(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())

    assert _export(tmp_store)[1]["capture"]["omitted_fields"] is None


def test_header_reports_zero_erasures_on_an_untouched_log(tmp_store: Store) -> None:
    tmp_store.insert_request(_record())

    assert _header(tmp_store)["chain"]["entries_erased_on_request"] == 0
