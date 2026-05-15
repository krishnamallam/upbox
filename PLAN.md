# upbox — execution plan

**Vision:** Wireshark for AI tools. One capture engine, many lenses (compliance, cost, prompt history, security, tool inventory, quality, debug replay). See `README.md` for the full lens roadmap. v0.1 ships the **foundation plus one lens** (live feed). Every later lens is a ~1-week sprint that reuses the same capture engine and storage.

**Goal:** ship `v0.1.0` by **15 July 2026**.

**Why that date:** EU AI Act full obligations begin **2 August 2026** and v0.2 (compliance lens) lands on enforcement eve. But v0.1 has to come first — and the foundation is what makes everything after v0.2 possible. The 18-day window is also the trend tailwind for the v0.2 launch.

**Scope discipline:** v0.1 ships the *capture engine* and the *live feed lens*. Nothing else. Every feature must answer either "is this part of capturing AI traffic?" or "is this part of the live feed?" Compliance exports, cost tracking, history search — all roadmap, not v0.1. The lens architecture is what lets them ship later as 1-week sprints.

---

## Stack decisions (locked)

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | mitmproxy is Python. No reason to add another language. |
| Package manager | `uv` | Faster than poetry. Simpler than pip-tools. |
| Proxy core | `mitmproxy` (MIT) | Battle-tested, addon API is clean, license-compatible. |
| DB | `sqlite3` stdlib + WAL | Schema is small. No ORM tax. |
| Web framework | `FastAPI` | Async, typed, fast. |
| Frontend | HTMX + Pico.css | No build step. No JS framework. Ships in days. |
| Dashboard pattern | Lens-routed (`/lens/{name}/...`) | One shell, many views. Adding a lens = new route + template + queries. No dashboard rewrite per feature. |
| CLI | `typer` | Type-hinted, autocomplete, ergonomic. |
| Config | YAML, editable from UI | Edit in editor or in browser, same source of truth. |
| Tests | pytest + pytest-asyncio | Standard. |
| Lint / format | `ruff` | Replaces flake8 + black + isort. |
| Type check | `mypy` strict on `upbox/` | Off in `tests/`. |
| CI | GitHub Actions | Linux + macOS, py3.12 + 3.13. |
| Release | PyPI + Homebrew tap | `pipx install upbox` is the canonical install. |

---

## File layout

```
upbox/
├── LICENSE                              # MIT — already present
├── README.md                            # already written
├── PLAN.md                              # this file
├── CHANGELOG.md
├── pyproject.toml
├── .python-version
├── .pre-commit-config.yaml
├── .gitignore
├── .github/
│   └── workflows/
│       ├── ci.yml                       # lint + test on PR
│       └── release.yml                  # PyPI publish on tag
├── upbox/
│   ├── __init__.py
│   ├── __main__.py                      # `python -m upbox` → cli.app()
│   ├── cli.py                           # typer CLI: init, start, stop, status, export
│   ├── config.py                        # config dataclasses + YAML loader
│   ├── ca.py                            # generate / install / uninstall local CA
│   ├── proxy.py                         # mitmproxy bootstrap (loads addons)
│   ├── addons/
│   │   ├── __init__.py
│   │   ├── capture.py                   # persists every flow to SQLite
│   │   ├── fingerprint.py               # detects which tool the request is from
│   │   ├── redact.py                    # applies regex redactions in-flight
│   │   └── enforce.py                   # domain allowlist enforcement
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.sql
│   │   └── store.py                     # sqlite wrapper (insert, query, export)
│   ├── rules/
│   │   ├── tools.yaml                   # tool fingerprints (UA, host, headers)
│   │   ├── redact.yaml                  # default redaction patterns
│   │   └── allowlist.yaml               # default domain policies
│   ├── dashboard/
│   │   ├── __init__.py
│   │   ├── app.py                       # FastAPI app
│   │   ├── lenses.py                    # lens registry (name → template dir + handler)
│   │   ├── routes.py                    # /lens/{name}/... dispatch
│   │   ├── templates/
│   │   │   ├── base.html                # shell with lens picker in nav
│   │   │   ├── lenses/
│   │   │   │   └── live/                # live feed lens (only one in v0.1)
│   │   │   │       ├── index.html
│   │   │   │       ├── request.html
│   │   │   │       └── partials/
│   │   └── static/
│   │       ├── pico.css
│   │       └── htmx.min.js
│   └── compliance/
│       ├── __init__.py
│       └── aiact.py                     # Article 26 export format (v0.2)
├── tests/
│   ├── conftest.py
│   ├── test_ca.py
│   ├── test_fingerprint.py
│   ├── test_redact.py
│   ├── test_store.py
│   ├── test_export.py
│   └── fixtures/
│       ├── cursor_flow.bin
│       ├── claude_flow.bin
│       └── copilot_flow.bin
├── docs/
│   ├── installing-ca.md
│   ├── configuring-tools.md             # per-tool setup
│   ├── redaction-rules.md
│   ├── ai-act-mapping.md
│   └── faq.md
└── LICENSES/
    ├── mitmproxy-LICENSE
    ├── fastapi-LICENSE
    ├── htmx-LICENSE
    └── pico-LICENSE
```

---

## 14-day build plan

Trunk-based. One commit minimum per day. No long-lived branches. CI passes before any push.

### Day 1 — Scaffold

**Outcome:** `uv sync && upbox --help` works.

- Initialise `pyproject.toml` (Python 3.12+, deps: `mitmproxy`, `fastapi`, `uvicorn[standard]`, `typer`, `pyyaml`, `jinja2`).
- `.pre-commit-config.yaml`: ruff lint+format, mypy.
- `.github/workflows/ci.yml`: lint + type-check + test, matrix on Linux/macOS, py3.12.
- `upbox/cli.py` skeleton: `init`, `start`, `stop`, `status`, `export` as stubs.
- `tests/conftest.py` + one smoke test (`test_cli_help`).
- Commit: `chore: project scaffold`.

### Day 2 — Local CA

**Outcome:** `upbox init` generates a CA and installs it to the system trust store on macOS + Linux.

- `upbox/ca.py`: generate cert + key in `~/.upbox/ca/` using `cryptography`.
- macOS: `security add-trusted-cert` (sudo prompt is fine).
- Linux: copy to `/usr/local/share/ca-certificates/` + `update-ca-certificates`.
- Windows: ship clear manual instructions (defer auto-install to v0.2).
- `upbox init --uninstall` reverses the install.
- Tests: cert generation only (no system install in CI).
- Commit: `feat(ca): generate and install local CA`.

### Day 3 — Capture

**Outcome:** `upbox start` boots mitmproxy; every flow lands in SQLite.

- `upbox/db/schema.sql`:
  ```sql
  CREATE TABLE requests (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    tool TEXT,
    method TEXT,
    scheme TEXT,
    host TEXT,
    path TEXT,
    req_bytes INTEGER,
    resp_bytes INTEGER,
    status INTEGER,
    headers_json TEXT,
    body_excerpt TEXT,
    body_hash TEXT,
    redactions_applied_json TEXT,
    blocked INTEGER DEFAULT 0
  );
  CREATE INDEX idx_requests_ts ON requests(ts);
  CREATE INDEX idx_requests_tool ON requests(tool);
  CREATE INDEX idx_requests_host ON requests(host);
  ```
- `upbox/db/store.py`: `insert_request`, `query_recent`, `export_jsonl`, `export_csv`. WAL mode.
- `upbox/addons/capture.py`: mitmproxy addon — `response()` hook → `store.insert_request`.
- `upbox/proxy.py`: `run()` starts mitmproxy with the capture addon loaded.
- Tests: in-memory SQLite, fake mitmproxy flow → exactly 1 row, correct fields.
- Commit: `feat(capture): persist every flow to SQLite`.

### Day 4 — Tool fingerprinting

**Outcome:** Requests are tagged with `tool` (Cursor, Claude, Copilot, etc.).

- `upbox/rules/tools.yaml`:
  ```yaml
  - name: Cursor
    match:
      ua_contains: ["Cursor/"]
      hosts: ["api.cursor.sh", "api2.cursor.sh"]
  - name: Claude Code
    match:
      ua_contains: ["claude-code", "anthropic-ai/sdk"]
      hosts: ["api.anthropic.com"]
  - name: GitHub Copilot
    match:
      ua_contains: ["GitHubCopilot", "copilot-"]
      hosts: ["api.githubcopilot.com", "copilot-proxy.githubusercontent.com"]
  - name: Claude Desktop
    match:
      hosts: ["api.anthropic.com"]
      headers: ["x-app: claude-desktop"]
  - name: ChatGPT
    match:
      hosts: ["chat.openai.com", "chatgpt.com"]
      ua_contains: ["ChatGPT"]
  - name: Codeium
    match:
      ua_contains: ["codeium"]
      hosts: ["server.codeium.com"]
  ```
- `upbox/addons/fingerprint.py`: load YAML, classify each flow, attach `tool` tag before capture writes.
- Tests: synthetic flow per tool → correct classification.
- Commit: `feat(fingerprint): classify flows by AI tool`.

### Day 5 — Lens-aware dashboard + live feed lens

**Outcome:** `http://127.0.0.1:8800/lens/live` shows a live feed of requests. The dashboard is lens-aware from day one — adding lenses in v0.2+ requires no dashboard rewrite.

- `upbox/dashboard/app.py`: FastAPI mount; lifespan hook starts mitmproxy in a background thread.
- `upbox/dashboard/lenses.py`: lens registry. A lens is a name + template directory + dict of route handlers. Live feed is the only lens registered in v0.1.
- `templates/base.html`: shell with Pico.css + lens picker in the nav (only "Live feed" enabled).
- `templates/lenses/live/index.html`: per-tool tiles (count + bytes) + scrolling request list.
- HTMX polls `/lens/live/recent` every 2 seconds.
- `routes.py`: `GET /` redirects to default lens (`/lens/live`); `GET /lens/{name}/...` dispatches to the lens handler.
- Commit: `feat(dashboard): lens-aware shell + live feed lens`.

**Why this matters:** the compliance, cost, history, security, tool-inventory, quality, and debug-replay lenses all plug into this exact shell post-v0.1. Each future lens is a new directory under `templates/lenses/` plus a handler in the registry. The capture engine never changes.

### Day 6 — Request detail

**Outcome:** Click a row → see full headers, body excerpt, host, timing.

- `GET /requests/{id}` → `request.html` partial.
- HTMX swap into a side panel; no full reload.
- Show: tool, method, host, path, status, timing, headers (collapsible), body excerpt (first 4 KB, with toggle to load full from disk).
- Commit: `feat(dashboard): per-request detail view`.

### Day 7 — Redaction engine

**Outcome:** Configurable regex redactions strip secrets *before* forwarding.

- `upbox/rules/redact.yaml`:
  ```yaml
  - name: aws-access-key
    pattern: "AKIA[0-9A-Z]{16}"
    replace: "[REDACTED:aws-access-key]"
  - name: openai-key
    pattern: "sk-[A-Za-z0-9]{32,}"
    replace: "[REDACTED:openai-key]"
  - name: anthropic-key
    pattern: "sk-ant-[A-Za-z0-9-]{32,}"
    replace: "[REDACTED:anthropic-key]"
  - name: dotenv-block
    pattern: "^[A-Z_][A-Z0-9_]*=.+$"
    multiline: true
    replace: "[REDACTED:env-var]"
  ```
- `upbox/addons/redact.py`: apply patterns to the request body in the `request()` hook; record what was redacted in `redactions_applied_json`.
- Dashboard preview mode: show what *would* be redacted without enabling the rule.
- Tests: each pattern + a combined-pattern test on a realistic prompt.
- Commit: `feat(redact): regex redaction engine`.

### Day 8 — Domain allowlist

**Outcome:** Per-tool, requests to unknown destinations get blocked or flagged.

- `upbox/rules/allowlist.yaml`:
  ```yaml
  Cursor:
    allow: [api.cursor.sh, api2.cursor.sh]
    block_unknown: warn   # warn | block
  Claude Code:
    allow: [api.anthropic.com]
    block_unknown: warn
  default:
    block_unknown: warn
  ```
- `upbox/addons/enforce.py`: check destination; mark `blocked=1` and short-circuit if policy is `block`.
- Dashboard: red row for blocked, yellow for warn.
- Tests: synthetic flows + allowlist permutations.
- Commit: `feat(enforce): domain allowlist per tool`.

### Day 9 — Polish pass

**Outcome:** It feels nice. Empty states, loading states, settings.

- Empty state: "Configure your first AI tool to see traffic" → links to docs.
- Settings page: edit `redact.yaml` + `allowlist.yaml` from the UI; save back to disk.
- Live-edit reload (mitmproxy addon detects YAML mtime change and reloads rules).
- Keyboard shortcuts: `/` to search, `r` to refresh, `Esc` to close detail panel.
- Commit: `feat(dashboard): polish + live-edit rules`.

### Day 10 — Real-world test + the screenshot

**Outcome:** Run a real session. Capture the launch screenshot.

- Configure Cursor, Claude desktop, and ChatGPT to use the upbox proxy.
- Use them naturally for ~30 minutes of real work.
- Identify and fix the worst bugs (some will exist).
- Take the launch screenshot — top tiles + per-tool table + a striking request.
- Iterate the dashboard UI until the screenshot pops.
- Commit: `fix: real-world bugs + UI polish for launch shot`.

### Day 11 — Audit log export

**Outcome:** `upbox export --format jsonl|csv` works.

- `upbox/cli.py` `export` subcommand: `--format`, `--since`, `--until`, `--tool`, `-o`.
- JSONL output (one request per line, stable field order).
- CSV output (Excel-friendly column names).
- Tests: golden-file comparisons.
- Commit: `feat(export): JSONL + CSV audit log export`.

### Day 12 — Docs + Windows manual setup

**Outcome:** A new user goes from `pipx install upbox` to first captured request in **under 5 minutes**.

- Polish `README.md` so every command is accurate.
- `docs/installing-ca.md` — macOS, Linux, Windows.
- `docs/configuring-tools.md` — per-tool screenshots and commands.
- `docs/redaction-rules.md` — how to write custom rules.
- `docs/ai-act-mapping.md` — expanded from README.
- `docs/faq.md` — performance, HTTPS pinning, what doesn't work.
- Commit: `docs: complete setup guide`.

### Day 13 — Buffer / launch prep

**Outcome:** Everything works. Launch assets ready.

- Run upbox for a full work day. Note every annoyance. Fix the top 3.
- Draft the launch X thread: screenshot + 3-line story + repo link → `launch/x-thread.md`.
- Draft the HN Show post → `launch/hn.md`.
- Draft the r/selfhosted + r/privacy crosspost → `launch/reddit.md`.
- Build the launch screenshot (real data, real story, real numbers).
- PyPI publish dry-run.
- Commit: `chore: launch assets`.

### Day 14 — Ship

**Outcome:** `v0.1.0` tagged, pushed, posted.

- Bump version to `0.1.0`; update `CHANGELOG.md`.
- `git tag v0.1.0 && git push --tags`.
- `release.yml` publishes to PyPI on tag push.
- Submit to HN Show, post the X thread, crosspost to Reddit.
- Monitor for 6+ hours; reply to every comment in the first 90 minutes.
- Commit: `release: v0.1.0`.

---

## Post-v0.1 lens roadmap

Each lens is a ~1-week sprint. The capture engine and storage from v0.1 don't change. A new lens = one directory under `templates/lenses/` + a handler in the registry + lens-specific queries on the existing audit-log schema.

Dates after v0.2 are intentions, not commitments. Early-adopter signal decides the order.

### v0.2 — Compliance lens (target: 1 August 2026, eve of EU AI Act enforcement)
- Routes: `/lens/compliance/`, `/lens/compliance/eu-ai-act`, `/lens/compliance/gdpr`, `/lens/compliance/soc2`
- Export formats: EU AI Act Article 26 schema (or best-effort if EU has not published a canonical one), GDPR Article 5 data minimisation report, SOC 2 CC6.1 / CC7.2 access log, ISO 27001 A.5.30 logs
- Tamper-evident hash chain on the audit log (each row hashes the previous row's hash; tampering breaks the chain)
- Encrypted-at-rest SQLite (sqlcipher or app-layer encryption)
- Configurable retention policies (auto-purge after N days, by tool, by host)

### v0.3 — Cost lens (target: mid–late August 2026)
- Routes: `/lens/cost/`, `/lens/cost/by-tool`, `/lens/cost/by-model`, `/lens/cost/alerts`
- Per-request token estimation (input + output tokens from OpenAI / Anthropic / Google response bodies)
- Pricing table for known models, refreshed quarterly via PR
- Daily / weekly / monthly spend by tool, model, and detected repo
- Budget alerts (configurable threshold per tool)

### v0.4 — Prompt history lens (target: September 2026)
- Routes: `/lens/history/`, `/lens/history/search`
- Full-text search over prompts and responses (SQLite FTS5)
- Filters by tool, time range, host, detected repo
- "What did I ask Cursor about Postgres last Tuesday?" → full thread reconstruction

### v0.5 — Security lens (target: September–October 2026)
- Routes: `/lens/security/`, `/lens/security/secrets`, `/lens/security/egress`
- Built on the redaction engine's detections — surfaces what was redacted, when, from where
- Anomaly alerts: tool calling a domain not in its allowlist, request body 10× baseline, etc.
- Source-code egress flags: prompts containing recognisable code patterns from your repos

### v0.6 — Tool inventory lens (target: October 2026)
- Routes: `/lens/tools/`, `/lens/tools/discovered`
- Auto-discovery: shows AI tools that have called known LLM hosts even before they are configured as fingerprints
- Active vs. dormant tools, last seen, frequency
- Team mode (v1.0 prerequisite): roll up multiple endpoints to one inventory

### v0.7 — Quality / fine-tuning lens (target: November 2026)
- Routes: `/lens/quality/`, `/lens/quality/curate`
- Mark interactions as good / bad / interesting
- Export curated sets as JSONL for OpenAI / Hugging Face / Axolotl fine-tuning formats
- Quality signals: response length, follow-up patterns, deletion patterns from the editor (if reachable)

### v0.8 — Debug replay lens (target: December 2026)
- Routes: `/lens/debug/`, `/lens/debug/replay`
- Re-issue a captured request to the live API (or to a different model) and diff responses
- Bisect mode: replay the same request 10× to see response variance
- Useful when an AI tool "used to work" and now doesn't

### v1.0 — platform graduation (target: early 2027)
- Plugin SDK locked: third parties ship lenses as installable packages
- macOS menu-bar app, Windows tray app
- Enterprise team mode (LAN-local central dashboard with auth — still no cloud)
- Browser extension companion for web-only AI tools (ChatGPT web, Claude web, Gemini web)
- Better Windows experience (auto CA install)

---

## Launch narrative — eight viral arcs from one codebase

The lens model isn't just an engineering pattern — it's a sustained-launch strategy. Each lens is its own launch moment, its own audience, its own narrative.

**Arc 1 — v0.1, Day 14: personal paranoia.**

> "I just installed upbox and watched Cursor send 4,200 lines of my private repo to 3 different domains in 30 seconds. Here's the dashboard. Open source, runs entirely on your machine."
>
> HN: *Upbox — Wireshark for your AI tools*.

**Arc 2 — v0.2, eve of EU AI Act enforcement (1 Aug 2026): compliance.**

> "Upbox v0.2 ships the compliance lens. Export every AI request as a tamper-evident audit log against EU AI Act Article 26, GDPR Article 5, SOC 2 CC6.1, ISO 27001 A.5.30. The deadline is tomorrow."
>
> HN: *Upbox v0.2 — Endpoint AI logging for AI Act, GDPR, SOC 2, ISO 27001*.

**Arc 3 — v0.3: cost.**

> "I ran upbox for a week and discovered I was spending $340/month on Cursor's o1 calls without realising. The cost lens is live."

**Arc 4–8** — prompt history, security, tool inventory, quality, debug replay. Each one has its own audience, its own headline, its own viral hook.

Eight arcs over six months. Same codebase. The lens architecture is the launch strategy.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Some AI tools pin certificates and reject the local CA | Document which ones work; ship a clear "what won't work" doc. v0.1 covers tools that *do* work (Cursor, Copilot via VSCode, ChatGPT web, OpenAI/Anthropic API clients). |
| mitmproxy performance under heavy AI traffic | Profile on day 10. Cap stored body excerpt at 4 KB. Drop request bodies entirely past a configurable size. WAL mode + batched inserts. |
| CA install on Windows is fiddly | Defer auto-install to v0.2; ship clear manual docs in v0.1. |
| The launch lands flat | Two-arc plan is the insurance. Two shots, not one. |
| Name collision: `upbox.dev` / npm `upbox` / PyPI `upbox` taken | Verify on day 0 (before Day 1). Fallbacks: `upbox-cli`, `outbox-ai`, `prompttoll`. |

---

## Out of scope for v0.1 (explicit)

These are roadmap, not v0.1. Cutting them is what makes 14 days realistic.

- Cloud sync (anything but local-only)
- Browser extension companion
- macOS menu-bar app / Windows tray app
- Auth / multi-user
- Real-time alerting (Slack, email, webhooks)
- Mobile
- Anything that requires writing TypeScript or maintaining a JS build

---

## Hand-off to Claude Code

This file is the contract. In Claude Code, run:

> *"Execute `PLAN.md`. Start with Day 1. After each day's commit, stop and wait for me to review before starting the next."*

That gives you a daily checkpoint. If a day's work drifts, you catch it before it compounds across the sprint.
