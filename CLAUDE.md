# upbox

Local proxy + dashboard that audits what AI tools send to the cloud. MIT. See `README.md` for the pitch, `PLAN.md` for the 14-day build.

## Commands

```bash
uv sync                                 # install deps
uv run pytest                           # full suite
uv run pytest tests/test_capture.py     # single file
uv run ruff check . && uv run ruff format .
uv run mypy upbox
uv run upbox start                      # proxy + dashboard
```

## Key Decisions

- **mitmproxy as the proxy core** (MIT). Use its addon API; never fork.
- **SQLite via stdlib `sqlite3` in WAL mode**. No ORM, schema is small.
- **HTMX + Pico.css, no build step**. Dashboard is server-rendered partials.
- **`127.0.0.1` only**. The dashboard must never bind a public interface.
- **No outbound calls from upbox itself** beyond the proxied requests it forwards.

## Don'ts

- Don't expand beyond `PLAN.md` v0.1 scope. v0.2 carries the compliance work.
- Don't log secrets, prompt bodies in full, or request bodies past the 4 KB cap.
- Don't bypass the redaction engine. If a flow can't be redacted safely, drop it.
