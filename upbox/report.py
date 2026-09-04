"""Subject-transparency report: what upbox holds about this machine's user.

One builder, two renderers. ``build_report`` reads the store and the live
capture and retention policies into a frozen dataclass; ``render_markdown``
turns it into the document a person can be handed for a GDPR Article 15
access request, and the dashboard renders the same dataclass as HTML.

The report is explicit about what it cannot say: who the controller is (the
deployer fills that in), whose personal data sits inside a prompt body (upbox
cannot separate a third party's from the user's), and whether the log is
complete (it records only what passed through the proxy).
"""

from __future__ import annotations

import getpass
import json
import platform
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from upbox import __version__
from upbox.addons.capture import CapturePolicy
from upbox.addons.capture import load_policy as load_capture_policy
from upbox.audit_export import COVERAGE_NOTE, TIMESTAMP_NOTE
from upbox.db.store import BODY_EXCERPT_MAX, Store
from upbox.retention import RetentionPolicy
from upbox.retention import load_policy as load_retention_policy


@dataclass(frozen=True)
class Recipient:
    tool: str
    host: str
    requests: int
    req_bytes: int
    first_seen: str
    last_seen: str


@dataclass(frozen=True)
class Erasure:
    request_ts: str
    erased_at: str
    reason: str


@dataclass(frozen=True)
class Checkpoint:
    ts: str
    seq_end: int
    head_hash: str


@dataclass(frozen=True)
class TransparencyReport:
    generated_at: str
    upbox_version: str
    hostname: str
    os_user: str
    database_path: str
    capture_bodies: bool
    capture_headers: bool
    rows_with_omitted_content: int
    body_days: int | None
    record_days: int | None
    rows_with_pruned_content: int
    entries_deleted_by_retention: int
    rows_under_legal_hold: int
    total_rows: int
    first_ts: str | None
    last_ts: str | None
    total_req_bytes: int
    body_excerpt_max: int
    recipients: tuple[Recipient, ...]
    erasures: tuple[Erasure, ...]
    chain_status: str
    chain_checked: int
    chain_entries_erased: int
    chain_head_hash: str
    last_checkpoint: Checkpoint | None


def build_report(
    store: Store,
    *,
    capture_policy: CapturePolicy | None = None,
    retention_policy: RetentionPolicy | None = None,
) -> TransparencyReport:
    """Read everything the report needs. Works on a read-only store."""
    capture = capture_policy if capture_policy is not None else load_capture_policy()
    retention = retention_policy if retention_policy is not None else load_retention_policy()
    summary = store.live_row_summary()
    verification = store.verify_chain()
    checkpoint = store.latest_checkpoint()
    return TransparencyReport(
        generated_at=datetime.now(UTC).isoformat(),
        upbox_version=__version__,
        hostname=platform.node() or "unknown",
        os_user=_os_user(),
        database_path=str(store.path),
        capture_bodies=capture.bodies,
        capture_headers=capture.headers,
        rows_with_omitted_content=store.omitted_content_count(),
        body_days=retention.body_days,
        record_days=retention.record_days,
        rows_with_pruned_content=store.pruned_content_count(),
        entries_deleted_by_retention=store.deleted_entry_count(),
        rows_under_legal_hold=store.legal_hold_count(),
        total_rows=int(summary["total"]),
        first_ts=summary["first_ts"],
        last_ts=summary["last_ts"],
        total_req_bytes=int(summary["total_bytes"]),
        body_excerpt_max=BODY_EXCERPT_MAX,
        recipients=tuple(
            Recipient(
                tool=str(row["tool"]),
                host=str(row["host"]),
                requests=int(row["requests"]),
                req_bytes=int(row["req_bytes"]),
                first_seen=str(row["first_seen"]),
                last_seen=str(row["last_seen"]),
            )
            for row in store.recipients()
        ),
        erasures=tuple(
            Erasure(
                request_ts=str(row["ts"]),
                erased_at=str(row["erased_at"]),
                reason=str(row["erased_reason"]),
            )
            for row in store.erasures()
        ),
        chain_status=verification.status,
        chain_checked=verification.checked,
        chain_entries_erased=verification.entries_erased,
        chain_head_hash=verification.head_hash,
        last_checkpoint=(
            Checkpoint(
                ts=str(checkpoint["ts"]),
                seq_end=int(checkpoint["seq_end"]),
                head_hash=str(checkpoint["head_hash"]),
            )
            if checkpoint is not None
            else None
        ),
    )


def _os_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def render_json(report: TransparencyReport) -> str:
    return json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n"


def render_markdown(report: TransparencyReport) -> str:
    """The hand-over document. Nine numbered sections, no em-dashes."""
    stored_headers = "stored" if report.capture_headers else "not stored (capture policy)"
    stored_bodies = "stored" if report.capture_bodies else "not stored (capture policy)"
    span = (
        f" between {report.first_ts} and {report.last_ts}"
        if report.first_ts and report.last_ts
        else ""
    )
    lines: list[str] = [
        "# What upbox holds about this machine's user",
        "",
        f"Generated {report.generated_at} by upbox {report.upbox_version} on host "
        f"`{report.hostname}` for OS user `{report.os_user}`. Database: "
        f"`{report.database_path}`.",
        "",
        "Controller and contact: to be completed by the deployer. upbox cannot know who is "
        "responsible for this installation.",
        "",
        "## 1. Purpose",
        "",
        "upbox is a deployer-side network observer. It records the requests that AI tools on "
        "this machine make to their cloud services, replaces secrets before forwarding, and "
        "keeps a tamper-evident audit log so the machine's user and the organisation deploying "
        "upbox can see and control what left the machine. This report is not legal advice.",
        "",
        "## 2. Categories of data and whether they are stored",
        "",
        "| Category | Stored |",
        "|---|---|",
        "| Timestamp of each request (host wall clock) | stored |",
        "| Tool that made the request | stored |",
        "| Destination host | stored |",
        "| Path, with credential values in the query string removed | stored |",
        "| Request and response sizes, HTTP status | stored |",
        f"| Request headers, credential values replaced by a marker | {stored_headers} |",
        f"| Request body excerpt, up to {report.body_excerpt_max // 1024} KB after redaction "
        f"| {stored_bodies} |",
        "| SHA-256 of the full redacted body | stored |",
        "| Redaction and allowlist outcomes | stored |",
        "",
        f"Rows whose body or headers were never stored under the capture policy: "
        f"{report.rows_with_omitted_content}.",
        "",
        "## 3. Recipients",
        "",
        f"{report.total_rows} request(s) recorded{span}, {report.total_req_bytes} bytes of "
        "request data in total.",
        "",
    ]
    if report.recipients:
        lines += [
            "| Tool | Host | Requests | Bytes | First seen | Last seen |",
            "|---|---|---|---|---|---|",
        ]
        lines += [
            f"| {r.tool} | {r.host} | {r.requests} | {r.req_bytes} | {r.first_seen} "
            f"| {r.last_seen} |"
            for r in report.recipients
        ]
    else:
        lines.append("None recorded.")
    lines += [
        "",
        "## 4. Retention",
        "",
        f"- Bodies and headers: {_retention('cleared', report.body_days)}.",
        f"- Whole records: {_retention('deleted', report.record_days)}.",
        f"- Rows with content cleared by retention: {report.rows_with_pruned_content}.",
        f"- Entries deleted by retention (disclosed as chain gaps): "
        f"{report.entries_deleted_by_retention}.",
        f"- Rows under legal hold, exempt from retention: {report.rows_under_legal_hold}.",
        "",
        "## 5. Erasures on request",
        "",
    ]
    if report.erasures:
        lines.append(f"{len(report.erasures)} record(s) erased on request:")
        lines.append("")
        lines += [
            f"- Request at {e.request_ts}, erased {e.erased_at}. Reason: {e.reason}"
            for e in report.erasures
        ]
    else:
        lines.append("None.")
    lines += [
        "",
        "## 6. Integrity",
        "",
        f"- Hash chain: {report.chain_status}, {report.chain_checked} entries recomputed, "
        f"{report.chain_entries_erased} erased entries linked through.",
        f"- Chain head: `{report.chain_head_hash}`",
        (
            f"- Last checkpoint: {report.last_checkpoint.ts} at seq "
            f"{report.last_checkpoint.seq_end}, head `{report.last_checkpoint.head_hash}`"
            if report.last_checkpoint is not None
            else "- Last checkpoint: none. Run `upbox checkpoint` to seal the head."
        ),
        "",
        "## 7. Your rights and how to exercise them",
        "",
        "- A copy of the records: `upbox export --format audit -o records.ndjson`, or "
        "`upbox report --records records.ndjson`.",
        '- Erasure of specific records: `upbox erase --id N --reason "..."`. The erasure is '
        "disclosed in section 5 and in every later export.",
        "- Shorter retention: edit `~/.upbox/rules/retention.yaml`.",
        "- Storing less in the first place: set `bodies: false` and `headers: false` in "
        "`~/.upbox/rules/capture.yaml`.",
        "",
        "## 8. Limitations",
        "",
        f"- Coverage: {COVERAGE_NOTE}",
        "- A stored body may contain personal data about other people (a colleague's name in a "
        "prompt, an email in a file). upbox cannot separate their data from yours.",
        f"- Timestamps: {TIMESTAMP_NOTE}",
        "- Erasures are disclosed, not hidden. A tombstone keeps its position and hash so the "
        "log stays verifiable.",
        "",
        "## 9. About this report",
        "",
        "Generated by `upbox report`. The same information is available live at "
        "http://127.0.0.1:8800/transparency while upbox is running.",
        "",
    ]
    return "\n".join(lines)


def _retention(verb: str, days: int | None) -> str:
    return "kept indefinitely" if days is None else f"{verb} after {days} day(s)"
