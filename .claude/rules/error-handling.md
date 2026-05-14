---
paths:
  - "upbox/dashboard/**"
  - "upbox/addons/**"
  - "upbox/cli.py"
  - "upbox/proxy.py"
---

# Error Handling

- Use typed custom exception classes with codes, not generic `Exception("something went wrong")`.
- Never swallow errors silently. Log or re-raise with added context about which operation failed.
- Await every coroutine. No fire-and-forget async tasks unless wrapped in `asyncio.create_task` with an explicit done-callback.
- HTTP error responses: FastAPI `HTTPException` with structured `detail`; correct status codes (400 validation, 401 auth, 404 not found, 500 unexpected).
- Never expose stack traces, internal paths, or raw database errors in dashboard responses.
- Retry transient errors (network timeouts, rate limits) with exponential backoff. Fail fast on validation and auth errors — don't retry them.
- Include request or flow IDs in error logs when available.
- mitmproxy addon failures must not crash the proxy. Catch in the hook, log, and let the flow pass through (or block, per policy) — never let an exception kill the addon thread.
