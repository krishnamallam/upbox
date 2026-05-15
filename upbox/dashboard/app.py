"""upbox dashboard — FastAPI + Jinja2 + vanilla CSS + minimal JS.

Reads from ``~/.upbox/upbox.db``. Never touches mitmproxy directly. The proxy
runs in a separate process per the architecture decision; this side only
reads.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

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
        s = store(request)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "tools": s.per_tool_summary(),
                "rows": s.query_recent(limit=100),
            },
        )

    @app.get("/requests/recent", response_class=HTMLResponse)
    async def recent(request: Request) -> HTMLResponse:
        s = store(request)
        return templates.TemplateResponse(
            request,
            "partials/recent.html",
            {
                "tools": s.per_tool_summary(),
                "rows": s.query_recent(limit=100),
            },
        )

    @app.get("/requests/{request_id}", response_class=HTMLResponse)
    async def detail(request: Request, request_id: int) -> HTMLResponse:
        s = store(request)
        row = s.query_by_id(request_id)
        if row is None:
            raise HTTPException(status_code=404, detail="request not found")
        return templates.TemplateResponse(
            request,
            "partials/request_detail.html",
            {"row": row, "headers": _parse_headers(row["headers_json"])},
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


def run(host: str = "127.0.0.1", port: int = 8800) -> None:
    """Boot the dashboard. Blocks until Ctrl+C. ``127.0.0.1`` only — never bind public."""
    import uvicorn

    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError(f"dashboard must bind to loopback only, got {host!r}")

    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
