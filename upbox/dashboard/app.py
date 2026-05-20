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
from upbox.db.store import DEFAULT_DB_PATH, Store


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
        app.state.store = Store(db_path)
        try:
            yield
        finally:
            app.state.store.close()

    app = FastAPI(title="upbox dashboard", lifespan=lifespan)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    def store(request: Request) -> Store:
        result = request.app.state.store
        return result if isinstance(result, Store) else Store(db_path)

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
        return templates.TemplateResponse(
            request,
            "partials/request_detail.html",
            {
                "row": row,
                "headers": _parse_headers(row["headers_json"]),
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
_VALID_STATUSES = {"all", "forwarded", "redacted", "blocked"}
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
