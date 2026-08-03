"""upbox dashboard — FastAPI + Jinja2 + vanilla CSS + minimal JS.

Reads from ``~/.upbox/upbox.db``. Never touches mitmproxy directly. The proxy
runs in a separate process per the architecture decision; this side only
reads.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from upbox import settings
from upbox.dashboard.icons import icon_for
from upbox.db.store import BODY_EXCERPT_MAX, DEFAULT_DB_PATH, Store


def _resource_dir(name: str) -> Path:
    return Path(str(resources.files("upbox.dashboard").joinpath(name)))


TEMPLATES_DIR = _resource_dir("templates")
STATIC_DIR = _resource_dir("static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "—"
    n = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


templates.env.filters["bytes"] = _format_bytes
templates.env.globals["icon_for"] = icon_for


def _ago(ts: str | None) -> str:
    """Render a SQLite timestamp as a compact relative offset (e.g. ``-5s``).

    Falls back to the raw value if parsing fails — we'd rather show
    something than a blank cell.
    """
    if not ts:
        return "—"
    try:
        from datetime import UTC, datetime

        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        delta = datetime.now(UTC) - when
        seconds = int(delta.total_seconds())
    except (ValueError, TypeError):
        return ts
    if seconds < 60:
        return f"-{seconds}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"-{m}m {s}s"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    return f"-{h}h {m}m"


templates.env.filters["ago"] = _ago


def _from_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


templates.env.filters["from_json"] = _from_json


def _pretty_json(value: str | None) -> str | None:
    """Indent a JSON request body for display.

    AI tools send JSON as one compact line; rendered verbatim it's a wall of
    text. When the excerpt parses as JSON we re-emit it indented. When it does
    not (a non-JSON body, or one truncated past ``BODY_EXCERPT_MAX`` so the tail
    is incomplete) we return it unchanged rather than show nothing.
    ``ensure_ascii=False`` keeps unicode readable; the caller still escapes for
    HTML and highlights ``[REDACTED:...]`` tokens via ``redact_marks``.
    """
    if not value:
        return value
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return value
    return json.dumps(parsed, indent=2, ensure_ascii=False)


templates.env.filters["pretty_json"] = _pretty_json
templates.env.globals["body_excerpt_max"] = BODY_EXCERPT_MAX


def _format_body(value: str | None, content_type: str | None = None) -> str | None:
    """Format a request body for display, by content type.

    Single-object JSON is always indented (so a mislabeled body still reads
    well). Otherwise we branch on ``Content-Type`` for structured-but-not-single
    JSON bodies: NDJSON, SSE event streams, and form-encoded. Each formatter
    falls back to the raw text if it can't cleanly format, so the Body tab never
    shows worse than the verbatim excerpt and never raises. Output is unescaped
    plain text and MUST be rendered through the ``redact_marks`` filter, which
    HTML-escapes it and highlights ``[REDACTED:...]`` markers.
    """
    if not value:
        return value
    # content_type comes from stored headers and may be malformed (e.g. a list);
    # only a real string drives formatting, everything else falls through.
    if not isinstance(content_type, str):
        content_type = None
    pretty = _pretty_json(value)
    if pretty != value:
        return pretty
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    if ctype in {"application/x-ndjson", "application/jsonl", "application/x-jsonlines"}:
        return _format_ndjson(value) or value
    if ctype == "text/event-stream":
        return _format_sse(value) or value
    if ctype == "application/x-www-form-urlencoded":
        return _format_form(value) or value
    return value


def _format_ndjson(value: str) -> str | None:
    """Indent each line of an NDJSON / JSONL body. Returns None unless every
    non-empty line is valid JSON (otherwise the caller keeps the raw text)."""
    lines = [line.rstrip("\r") for line in value.split("\n") if line.strip()]
    if not lines:
        return None
    out: list[str] = []
    for line in lines:
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            return None
        out.append(json.dumps(obj, indent=2, ensure_ascii=False))
    return "\n\n".join(out)


def _format_sse(value: str) -> str | None:
    """Indent the JSON payload of each ``data:`` line in an SSE body. Non-data
    lines are kept as-is. Returns None if no data line carried JSON."""
    formatted_any = False
    out: list[str] = []
    for raw_line in value.split("\n"):
        line = raw_line.rstrip("\r")
        stripped = line.strip()
        if stripped.startswith("data:"):
            payload = stripped[len("data:") :].strip()
            try:
                obj = json.loads(payload)
            except (ValueError, TypeError):
                out.append(line)
                continue
            formatted_any = True
            out.append("data: " + json.dumps(obj, indent=2, ensure_ascii=False))
        else:
            out.append(line)
    return "\n".join(out) if formatted_any else None


def _format_form(value: str) -> str | None:
    """Render a urlencoded body as ``key = value`` lines, one per ``&`` segment.

    Shows the raw (still-encoded) key/value so the audit view reflects exactly
    what was sent, not a decoded interpretation. Returns None unless every
    segment is a real ``key=value`` pair, so prose or partial bodies fall back
    to verbatim. The alignment column is capped so one very long key can't pad
    every other line and balloon the rendered size.
    """
    pairs: list[tuple[str, str]] = []
    for segment in value.split("&"):
        if "=" not in segment:
            return None
        key, val = segment.split("=", 1)
        pairs.append((key, val))
    width = min(max(len(key) for key, _ in pairs), 40)
    return "\n".join(f"{key.ljust(width)} = {val}" for key, val in pairs)


templates.env.filters["format_body"] = _format_body


_REDACT_TOKEN_RE = re.compile(r"\[REDACTED:[A-Za-z0-9._\- ]{1,60}\]")


def _redact_marks(value: str | None) -> Markup:
    """Highlight ``[REDACTED:<rule>]`` tokens in a body excerpt.

    The body is HTML-escaped first, then each token (matched on the
    pre-escape source so we're not chasing escape sequences) is wrapped in
    ``<span class="red">…</span>``. We accept only ``A-Z 0-9 . _ - space``
    inside the brackets and cap the rule name at 60 chars so the regex can't
    be tricked into eating template tags or producing huge spans.
    """
    if not value:
        return Markup("")
    escaped = escape(value)
    return Markup(
        _REDACT_TOKEN_RE.sub(
            lambda m: f'<span class="red">{escape(m.group(0))}</span>',
            str(escaped),
        )
    )


templates.env.filters["redact_marks"] = _redact_marks


def create_app(db_path: Path = DEFAULT_DB_PATH) -> FastAPI:
    """Build the FastAPI app. The store is opened in the lifespan handler."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Read-only: the proxy is the sole writer. A write from here would
        # advance the log without advancing the hash chain, which verifies as
        # tampering.
        app.state.store = Store(db_path, read_only=True)
        try:
            yield
        finally:
            app.state.store.close()

    app = FastAPI(title="upbox dashboard", lifespan=lifespan)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def store(request: Request) -> Store:
        result = request.app.state.store
        return result if isinstance(result, Store) else Store(db_path, read_only=True)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        f = _read_filters(request)
        s = store(request)
        rows = s.query_filtered(
            since=_range_to_since(f["range"]),
            tool=f["tool"],
            status=f["status"],
            search=f["query"],
            order="DESC",
            limit=100,
        )
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "tools": s.per_tool_summary(),
                "rows": rows,
                "stats": s.dashboard_stats(),
                "selected_tool": f["tool"],
                "current_status": f["status"],
                "current_range": f["range"],
                "current_query": f["query"],
                "visible_count": len(rows),
                "bind": "127.0.0.1",
            },
        )

    @app.get("/requests/recent", response_class=HTMLResponse)
    async def recent(request: Request) -> HTMLResponse:
        f = _read_filters(request)
        s = store(request)
        rows = s.query_filtered(
            since=_range_to_since(f["range"]),
            tool=f["tool"],
            status=f["status"],
            search=f["query"],
            order="DESC",
            limit=100,
        )
        return templates.TemplateResponse(
            request,
            "partials/feed.html",
            {
                "rows": rows,
                "selected_tool": f["tool"],
                "current_status": f["status"],
                "current_range": f["range"],
                "current_query": f["query"],
            },
        )

    @app.get("/sidebar", response_class=HTMLResponse)
    async def sidebar(request: Request) -> HTMLResponse:
        s = store(request)
        return templates.TemplateResponse(
            request,
            "partials/sidebar.html",
            {
                "tools": s.per_tool_summary(),
                "selected_tool": request.query_params.get("tool") or None,
            },
        )

    @app.get("/stats", response_class=HTMLResponse)
    async def stats(request: Request) -> HTMLResponse:
        f = _read_filters(request)
        s = store(request)
        return templates.TemplateResponse(
            request,
            "partials/stats_bar.html",
            {
                "stats": s.dashboard_stats(),
                "bind": "127.0.0.1",
                "current_status": f["status"],
                "current_range": f["range"],
                "selected_tool": f["tool"],
                "current_query": f["query"],
            },
        )

    @app.get("/requests/{request_id}", response_class=HTMLResponse)
    async def detail(
        request: Request,
        request_id: int,
    ) -> HTMLResponse:
        s = store(request)
        row = s.query_by_id(request_id)
        if row is None:
            raise HTTPException(status_code=404, detail="request not found")
        requested_tab = request.query_params.get("tab", "body")
        if requested_tab not in _VALID_DETAIL_TABS:
            requested_tab = "body"
        headers = _parse_headers(row["headers_json"])
        content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), None)
        return templates.TemplateResponse(
            request,
            "partials/request_detail.html",
            {
                "row": row,
                "headers": headers,
                "content_type": content_type,
                "active_tab": requested_tab,
            },
        )

    @app.get("/export")
    async def export_jsonl(request: Request) -> StreamingResponse:
        """Stream the filtered feed as JSONL for download.

        Mirrors the ``/`` filters (range, status, tool, search) so the user
        gets exactly the rows they're looking at. No body bytes — only the
        audit-row excerpts already in the store.
        """
        f = _read_filters(request)
        s = store(request)
        rows = s.query_filtered(
            since=_range_to_since(f["range"]),
            tool=f["tool"],
            status=f["status"],
            search=f["query"],
        )

        def stream() -> Iterator[str]:
            for row in rows:
                yield json.dumps(dict(row)) + "\n"

        return StreamingResponse(
            stream(),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": 'attachment; filename="upbox-audit.jsonl"'},
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "tools_yaml": settings.read_current("tools"),
                "redact_yaml": settings.read_current("redact"),
                "allowlist_yaml": settings.read_current("allowlist"),
                "message": None,
                "error": None,
            },
        )

    @app.post("/settings/{kind}", response_class=HTMLResponse)
    async def settings_save(
        request: Request,
        kind: str,
        content: str = Form(...),
    ) -> HTMLResponse:
        ok, msg = settings.validate_and_write(kind, content)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "tools_yaml": settings.read_current("tools"),
                "redact_yaml": settings.read_current("redact"),
                "allowlist_yaml": settings.read_current("allowlist"),
                "message": msg if ok else None,
                "error": None if ok else msg,
            },
        )

    return app


def _parse_headers(headers_json: str | None) -> dict[str, Any]:
    if not headers_json:
        return {}
    try:
        result = json.loads(headers_json)
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        return {}


_VALID_RANGES = {"5m", "1h", "24h", "All"}
_VALID_STATUSES = {"all", "forwarded", "redacted", "flagged", "blocked"}
_VALID_DETAIL_TABS = {"body", "headers", "redactions", "allow", "export"}


def _read_filters(request: Request) -> dict[str, str | None]:
    """Pull and validate the four feed filters from the query string.

    Unknown values fall back to ``None`` (or ``"All"`` / ``"all"`` for the
    segment filters) so a malformed query string never produces a 500. Query
    text is capped at 200 chars to keep LIKE comparisons cheap.
    """
    qp = request.query_params
    raw_range = qp.get("range") or "All"
    raw_status = qp.get("status") or "all"
    return {
        "range": raw_range if raw_range in _VALID_RANGES else "All",
        "status": raw_status if raw_status in _VALID_STATUSES else "all",
        "tool": (qp.get("tool") or "").strip() or None,
        "query": (qp.get("q") or "").strip()[:200] or None,
    }


def _range_to_since(range_str: str | None) -> str | None:
    """Convert a UI range label (``5m`` / ``1h`` / ``24h`` / ``All``) to an
    ISO timestamp matching the capture addon's ``datetime.now(UTC).isoformat()``
    storage format. ``All`` and unknown values map to ``None`` (no lower bound).
    """
    if not range_str or range_str == "All":
        return None
    from datetime import UTC, datetime, timedelta

    deltas = {
        "5m": timedelta(minutes=5),
        "1h": timedelta(hours=1),
        "24h": timedelta(hours=24),
    }
    delta = deltas.get(range_str)
    if delta is None:
        return None
    return (datetime.now(UTC) - delta).isoformat()


def run(host: str = "127.0.0.1", port: int = 8800) -> None:
    """Boot the dashboard. Blocks until Ctrl+C. ``127.0.0.1`` only — never bind public."""
    import uvicorn

    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError(f"dashboard must bind to loopback only, got {host!r}")

    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
