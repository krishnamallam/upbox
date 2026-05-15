# HN Show post

**Title (under 80 chars):**

Show HN: upbox – See what your AI tools are actually sending

---

**Body:**

I built upbox because every time I tab-complete in Cursor or paste into
Claude, I'm not sure what's actually leaving my machine. The vendor
docs are vague and the tools themselves don't surface it. upbox is a
local proxy + dashboard that records every request your AI tools make,
strips obvious secrets before forwarding, and shows you what
happened.

It's MIT licensed, single Python process (mitmproxy core, FastAPI
dashboard, SQLite audit log), runs on 127.0.0.1 only, and makes zero
outbound calls of its own.

What v0.1 includes:

- Per-tool fingerprinting for Cursor, Claude (desktop + Code), Copilot,
  ChatGPT, Codeium, plus generic OpenAI / Anthropic / Gemini fallbacks.
- Content-aware redaction. Reads `Content-Type` and parses JSON properly
  so gzipped or nested-field secrets don't slip through. Defaults catch
  AWS / OpenAI / Anthropic / GitHub keys and dotenv lines.
- Per-tool destination allowlist (warn or block).
- Live dashboard with tiles, request list, click-through detail.
- Audit log export as JSONL or CSV, filterable by tool / time range.

Why now: EU AI Act full enforcement begins 2 August 2026. Most orgs
have policies; almost none have endpoint-level evidence. The bigger
arc is that "what is my AI tool actually doing" is going to be a
recurring question. v0.2 (the compliance lens — Article 26 export
format, tamper-evident hash chain, team mode) ships 1 August.

The dashboard runs on 127.0.0.1 and refuses to bind to any other host.
The CA is local, the user installs it, and the user can uninstall it.
The whole point is that the auditor has to be inspectable.

Install on Linux / macOS:

    pipx install upbox
    upbox init        # one-time CA install
    upbox start       # proxy on :8888, dashboard on :8800

Code: <repo URL>
Docs: <docs URL>

Built it over two weeks. The README has the full architecture
discussion and EU AI Act mapping. Happy to answer anything.
