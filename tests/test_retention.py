"""Tests for retention policy loading and pruning.

The load-bearing property: pruning must never leave the audit log looking
tampered with. Body clearing keeps the chain verifying outright, and record
deletion records a gap so verification can resume across it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from upbox.db.store import RequestRecord, Store
from upbox.retention import (
    DEFAULT_BODY_DAYS,
    RetentionPolicy,
    RetentionRunner,
    load_policy,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


@pytest.fixture
def tmp_store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.db")


def _record(ts: datetime, **overrides: object) -> RequestRecord:
    base: dict[str, object] = {
        "ts": ts.isoformat(),
        "tool": "cursor",
        "method": "POST",
        "scheme": "https",
        "host": "api.anthropic.com",
        "path": "/v1/messages",
        "req_bytes": 42,
        "resp_bytes": 100,
        "status": 200,
        "headers_json": '{"content-type": "application/json"}',
        "body_excerpt": '{"prompt": "secret"}',
        "body_hash": "deadbeef",
        "redactions_applied_json": None,
        "enforcement": None,
    }
    base.update(overrides)
    return RequestRecord(**base)  # type: ignore[arg-type]


def _seed(store: Store, ages_in_days: list[int]) -> None:
    for age in sorted(ages_in_days, reverse=True):
        store.insert_request(_record(NOW - timedelta(days=age)))


# --- policy loading --------------------------------------------------------


def test_missing_policy_file_yields_defaults(tmp_path: Path) -> None:
    assert load_policy(tmp_path / "absent.yaml").body_days == DEFAULT_BODY_DAYS


def test_policy_file_overrides_body_days(tmp_path: Path) -> None:
    path = tmp_path / "retention.yaml"
    path.write_text("body_days: 30\n")

    assert load_policy(path).body_days == 30


def test_null_body_days_disables_body_pruning(tmp_path: Path) -> None:
    path = tmp_path / "retention.yaml"
    path.write_text("body_days: null\n")

    assert load_policy(path).body_days is None


def test_malformed_policy_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "retention.yaml"
    path.write_text("body_days: not-a-number\n")

    assert load_policy(path).body_days == DEFAULT_BODY_DAYS


def test_non_mapping_policy_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "retention.yaml"
    path.write_text("- 1\n- 2\n")

    assert load_policy(path).body_days == DEFAULT_BODY_DAYS


def test_record_days_below_the_floor_warns() -> None:
    policy = RetentionPolicy(record_days=30, min_record_days=180)

    assert any("min_record_days" in note for note in policy.warnings())


def test_record_days_below_body_days_warns_it_is_pointless() -> None:
    policy = RetentionPolicy(body_days=90, record_days=30, min_record_days=1)

    assert any("has no effect" in note for note in policy.warnings())


def test_default_policy_has_no_warnings() -> None:
    assert RetentionPolicy().warnings() == []


def test_default_policy_never_deletes_rows() -> None:
    assert RetentionPolicy().record_days is None


# --- body pruning ----------------------------------------------------------


def test_prune_clears_bodies_past_the_cutoff(tmp_store: Store) -> None:
    _seed(tmp_store, [30])

    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert tmp_store.query_recent()[0]["body_excerpt"] is None


def test_prune_leaves_recent_bodies_alone(tmp_store: Store) -> None:
    _seed(tmp_store, [1])

    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert tmp_store.query_recent()[0]["body_excerpt"] is not None


def test_prune_clears_headers_too(tmp_store: Store) -> None:
    _seed(tmp_store, [30])

    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert tmp_store.query_recent()[0]["headers_json"] is None


def test_prune_keeps_the_body_digest(tmp_store: Store) -> None:
    """The digest is what keeps the pruned row evidentially useful."""
    _seed(tmp_store, [30])

    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert tmp_store.query_recent()[0]["body_excerpt_sha256"] is not None


def test_prune_keeps_the_row_metadata(tmp_store: Store) -> None:
    _seed(tmp_store, [30])

    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert tmp_store.query_recent()[0]["host"] == "api.anthropic.com"


def test_prune_records_when_it_cleared_the_row(tmp_store: Store) -> None:
    _seed(tmp_store, [30])

    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert tmp_store.query_recent()[0]["pruned_at"] is not None


def test_pruned_row_is_distinguishable_from_a_bodyless_request(tmp_store: Store) -> None:
    """A null body with no pruned_at means the request never had one."""
    tmp_store.insert_request(_record(NOW, body_excerpt=None, body_hash=None))

    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert tmp_store.query_recent()[0]["pruned_at"] is None


def test_body_pruning_keeps_the_chain_verifying(tmp_store: Store) -> None:
    """The whole reason the chain commits to digests instead of text."""
    _seed(tmp_store, [30, 20, 10])

    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert tmp_store.verify_chain().status == "ok"


def test_body_pruning_reports_content_as_unavailable(tmp_store: Store) -> None:
    _seed(tmp_store, [30])

    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert tmp_store.verify_chain().content_unavailable == 2


def test_prune_counts_the_rows_it_cleared(tmp_store: Store) -> None:
    _seed(tmp_store, [30, 20, 1])

    result = tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert result.bodies_cleared == 2


def test_prune_does_not_re_clear_an_already_pruned_row(tmp_store: Store) -> None:
    _seed(tmp_store, [30])
    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    second = tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert second.bodies_cleared == 0


def test_null_body_days_prunes_nothing(tmp_store: Store) -> None:
    _seed(tmp_store, [400])

    result = tmp_store.prune(RetentionPolicy(body_days=None), now=NOW)

    assert result.bodies_cleared == 0


# --- record deletion -------------------------------------------------------


def test_prune_deletes_rows_past_the_record_cutoff(tmp_store: Store) -> None:
    _seed(tmp_store, [500, 10])

    tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    assert len(tmp_store.query_filtered()) == 1


def test_record_deletion_counts_what_it_removed(tmp_store: Store) -> None:
    _seed(tmp_store, [500, 450, 10])

    result = tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    assert result.records_deleted == 2


def test_record_deletion_keeps_the_chain_verifiable(tmp_store: Store) -> None:
    """A recorded gap is a disclosed deletion, not a broken chain."""
    _seed(tmp_store, [500, 450, 10])

    tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    assert tmp_store.verify_chain().status == "ok"


def test_record_deletion_is_disclosed_by_verification(tmp_store: Store) -> None:
    _seed(tmp_store, [500, 450, 10])

    tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    assert tmp_store.verify_chain().entries_deleted == 2


def test_successive_prunes_leave_adjacent_gaps_that_still_verify(tmp_store: Store) -> None:
    """Daily retention makes this the normal case, not an edge case."""
    _seed(tmp_store, [500, 450, 300, 10])
    tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    tmp_store.prune(RetentionPolicy(body_days=None, record_days=200), now=NOW)

    assert tmp_store.verify_chain().status == "ok"


def test_successive_prunes_report_every_deleted_entry(tmp_store: Store) -> None:
    _seed(tmp_store, [500, 450, 300, 10])
    tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)
    tmp_store.prune(RetentionPolicy(body_days=None, record_days=200), now=NOW)

    assert tmp_store.verify_chain().entries_deleted == 3


def test_an_unrecorded_deletion_still_reads_as_tampering(tmp_store: Store) -> None:
    """Retention gets a gap record. A raw DELETE does not, and must break."""
    _seed(tmp_store, [500, 450, 10])

    tmp_store._conn.execute("DELETE FROM requests WHERE seq = 1")

    assert tmp_store.verify_chain().status == "broken"


def test_deleting_the_whole_log_leaves_a_verifiable_gap(tmp_store: Store) -> None:
    _seed(tmp_store, [500, 450])

    tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    assert tmp_store.verify_chain().status == "empty"


# --- legal hold ------------------------------------------------------------


def test_legal_hold_exempts_a_row_from_body_pruning(tmp_store: Store) -> None:
    _seed(tmp_store, [30])
    tmp_store.set_legal_hold()

    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert tmp_store.query_recent()[0]["body_excerpt"] is not None


def test_legal_hold_exempts_a_row_from_deletion(tmp_store: Store) -> None:
    _seed(tmp_store, [500])
    tmp_store.set_legal_hold()

    tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    assert len(tmp_store.query_filtered()) == 1


def test_legal_hold_can_be_scoped_to_a_range(tmp_store: Store) -> None:
    _seed(tmp_store, [30, 10])

    affected = tmp_store.set_legal_hold(since=(NOW - timedelta(days=20)).isoformat())

    assert affected == 1


def test_releasing_a_hold_lets_pruning_resume(tmp_store: Store) -> None:
    _seed(tmp_store, [30])
    tmp_store.set_legal_hold()
    tmp_store.set_legal_hold(held=False)

    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert tmp_store.query_recent()[0]["body_excerpt"] is None


def test_runner_prunes_on_a_single_pass(tmp_store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(tmp_store, [30])
    monkeypatch.setattr("upbox.retention.load_policy", lambda: RetentionPolicy(body_days=7))

    RetentionRunner(tmp_store).run_once()

    assert tmp_store.query_recent()[0]["body_excerpt"] is None


def test_runner_swallows_failures_to_keep_the_proxy_up(
    tmp_store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An addon exception must never take the proxy down."""

    def boom() -> RetentionPolicy:
        raise RuntimeError("synthetic policy failure")

    monkeypatch.setattr("upbox.retention.load_policy", boom)

    RetentionRunner(tmp_store).run_once()  # must not raise

    assert tmp_store.verify_chain().status == "empty"


# --- regressions from the v0.2 adversarial review --------------------------


def _insert_unchained(store: Store, ts: datetime) -> None:
    """A row as v0.1 would have written it: no seq, outside the chain."""
    store._conn.execute(
        "INSERT INTO requests (ts, host, method) VALUES (?, 'old.example', 'GET')",
        (ts.isoformat(),),
    )


def test_record_retention_deletes_pre_v02_rows(tmp_store: Store) -> None:
    """These are the oldest rows and the ones holding pre-fix credentials."""
    _insert_unchained(tmp_store, NOW - timedelta(days=500))

    tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    assert len(tmp_store.query_filtered()) == 0


def test_record_retention_counts_deleted_pre_v02_rows(tmp_store: Store) -> None:
    _insert_unchained(tmp_store, NOW - timedelta(days=500))

    result = tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    assert result.records_deleted == 1


def test_recent_pre_v02_rows_are_kept(tmp_store: Store) -> None:
    _insert_unchained(tmp_store, NOW - timedelta(days=10))

    tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    assert len(tmp_store.query_filtered()) == 1


def test_legal_hold_protects_a_pre_v02_row(tmp_store: Store) -> None:
    _insert_unchained(tmp_store, NOW - timedelta(days=500))
    tmp_store.set_legal_hold()

    tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    assert len(tmp_store.query_filtered()) == 1


def test_full_retention_prune_reports_what_it_deleted(tmp_store: Store) -> None:
    """This reported entries_deleted=0 into the auditor-facing export header."""
    _seed(tmp_store, [500, 450])

    tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    assert tmp_store.verify_chain().entries_deleted == 2


def test_dry_run_counts_bodies_it_would_clear(tmp_store: Store) -> None:
    _seed(tmp_store, [30, 1])

    assert tmp_store.preview_prune(RetentionPolicy(body_days=7), now=NOW).bodies_cleared == 1


def test_dry_run_counts_records_it_would_delete(tmp_store: Store) -> None:
    _seed(tmp_store, [500, 10])

    preview = tmp_store.preview_prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    assert preview.records_deleted == 1


def test_dry_run_changes_nothing(tmp_store: Store) -> None:
    _seed(tmp_store, [500])

    tmp_store.preview_prune(RetentionPolicy(body_days=7, record_days=400), now=NOW)

    assert tmp_store.query_recent()[0]["body_excerpt"] is not None


def test_dry_run_matches_what_prune_then_does(tmp_store: Store) -> None:
    _seed(tmp_store, [500, 450, 30, 1])
    policy = RetentionPolicy(body_days=7, record_days=400)
    preview = tmp_store.preview_prune(policy, now=NOW)

    actual = tmp_store.prune(policy, now=NOW)

    assert (preview.bodies_cleared, preview.records_deleted) == (
        actual.bodies_cleared,
        actual.records_deleted,
    )


def test_runner_survives_a_checkpoint_failure(
    tmp_store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raise here used to kill the asyncio task and disable retention."""
    _seed(tmp_store, [30])
    monkeypatch.setattr("upbox.retention.load_policy", lambda: RetentionPolicy(body_days=7))
    monkeypatch.setattr(
        tmp_store, "write_checkpoint", lambda reason: (_ for _ in ()).throw(RuntimeError("disk"))
    )

    RetentionRunner(tmp_store).run_once()  # must not raise

    assert tmp_store.query_recent()[0]["body_excerpt"] is None


def test_a_held_row_stops_the_deletion_run(tmp_store: Store) -> None:
    """Pruning around a hold would punch a second gap needing its own record."""
    _seed(tmp_store, [500, 450, 440])
    tmp_store.set_legal_hold(
        since=(NOW - timedelta(days=460)).isoformat(),
        until=(NOW - timedelta(days=440)).isoformat(),
    )

    tmp_store.prune(RetentionPolicy(body_days=None, record_days=400), now=NOW)

    assert len(tmp_store.query_filtered()) == 2


def test_prune_skips_rows_with_nothing_to_clear(tmp_store: Store) -> None:
    tmp_store.insert_request(
        _record(
            NOW - timedelta(days=30),
            body_excerpt=None,
            headers_json=None,
            omitted_fields='["body_excerpt", "headers_json"]',
        )
    )

    result = tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert result.bodies_cleared == 0


def test_prune_leaves_a_content_less_row_unstamped(tmp_store: Store) -> None:
    tmp_store.insert_request(
        _record(
            NOW - timedelta(days=30),
            body_excerpt=None,
            headers_json=None,
            omitted_fields='["body_excerpt", "headers_json"]',
        )
    )

    tmp_store.prune(RetentionPolicy(body_days=7), now=NOW)

    assert tmp_store.query_recent()[0]["pruned_at"] is None


def test_dry_run_skips_rows_with_nothing_to_clear(tmp_store: Store) -> None:
    tmp_store.insert_request(
        _record(
            NOW - timedelta(days=30),
            body_excerpt=None,
            headers_json=None,
            omitted_fields='["body_excerpt", "headers_json"]',
        )
    )

    preview = tmp_store.preview_prune(RetentionPolicy(body_days=7), now=NOW)

    assert preview.bodies_cleared == 0
