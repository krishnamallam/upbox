# upbox — execution plan

**Goal:** ship `v0.1.0` by **15 July 2026**.

**Why that date:** EU AI Act full obligations begin **2 August 2026**. The 18-day window between launch and enforcement is the trend tailwind. Arrive early, not on the day.

**Scope discipline:** v0.1 exists to make one screenshot real — the dashboard showing "Cursor sent N kB of code to M domains in the last 30 seconds." If a feature does not serve that screenshot, it is roadmap, not v0.1.

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
| CLI | `typer` | Type-hinted, autocomplete, ergonomic. |
| Config | YAML, editable from UI | Edit in editor or in browser, same source of truth. |
| Tests | pytest + pytest-asyncio | Standard. |
| Lint / format | `ruff` | Replaces flake8 + black + isort. |
| Type check | `mypy` strict on `upbox/` | Off in `tests/`. |
| CI | GitHub Actions | Linux + macOS, py3.12 + 3.13. |
| Release | PyPI + Homebrew tap | `pipx install upbox` is the canonical install. |
| Process model | Two processes, SQLite WAL as IPC | mitmproxy and FastAPI both want their own event loop. Threading them inside one process means broken signal handling and messy shutdown. See "Process architecture" below. |

---

## Process architecture

upbox runs as **two cooperating processes** plus a thin supervisor. They share `~/.upbox/upbox.db` (SQLite in WAL mode, multi-reader + single-writer).

```
                        upbox start (supervisor)
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
        upbox proxy                  upbox dashboard
        (mitmproxy main loop)        (uvicorn + FastAPI)
        port 8888                    port 8800 (127.0.0.1 only)
                │                           │
                └──────────┬────────────────┘
                           ▼
                    ~/.upbox/upbox.db
                    (SQLite WAL)
```

- **`upbox proxy`** — mitmproxy running as the main process with the upbox addons loaded (capture, fingerprint, redact, enforce). Owns the cert store. Writes flows to SQLite.
- **`upbox dashboard`** — uvicorn + FastAPI on `127.0.0.1:8800`. Reads SQLite. Never directly touches mitmproxy. HTMX polls `/lens/...` partials.
- **`upbox start`** — supervisor (~50 lines). Spawns both as subprocesses, forwards SIGINT / SIGTERM, exits non-zero if either dies. `upbox stop` cleans up.

**Why two processes:** mitmproxy is built around its own asyncio `Master` loop with its own signal handlers. So is uvicorn. Stuffing one inside the other's thread led to lost Ctrl+C, messy shutdowns, and addon hooks running on unexpected threads. Two processes is +50 lines of supervisor code and gets clean lifecycle, isolated crashes (if mitmproxy dies the dashboard still serves the last hour of data), and standard signal handling on both sides.

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
│   ├── ca.py                            # generate / install / uninstall local CA (system trust + NSS)
│   ├── supervisor.py                    # `upbox start` — spawns proxy + dashboard, forwards signals
│   ├── proxy.py                         # `upbox proxy` — mitmproxy main process (loads addons)
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
│   │   ├── routes.py
│   │   ├── templates/
│   │   │   ├── base.html
│   │   │   ├── index.html
│   │   │   ├── request.html
│   │   │   └── partials/
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

### Day 2 — Local CA + status doctor

**Outcome:** `upbox init` generates a CA and installs it everywhere the AI tools actually look. `upbox status` reports each layer so silent-CA-missing bugs surface immediately.

- `upbox/ca.py`: generate cert + key in `~/.upbox/ca/` using `cryptography`.
- macOS: `security add-trusted-cert` (sudo prompt is fine).
- **Linux (three cert stores — all needed):**
  - System trust: copy to `/usr/local/share/ca-certificates/` + `update-ca-certificates`. Covers curl, wget, system Python.
  - NSS: if `certutil` is on PATH, add to `~/.pki/nssdb/`. Covers Firefox, Chrome (sometimes), NSS-based Electron apps. If `certutil` missing, print install command and skip.
  - Electron / Node: print copy-pasteable launch hints for known apps (`NODE_EXTRA_CA_CERTS=$HOME/.upbox/ca/upbox-ca.pem cursor`, similar for Claude desktop, VSCode). Ship as a docs file too.
- Windows: ship clear manual instructions (defer auto-install to v0.2).
- `upbox init --uninstall` reverses every layer that was installed.
- **`upbox status`** doctor command: reports CA presence in each layer (system trust ✓ / NSS ✓ / env-var hint shown ✓), proxy port listening, dashboard port listening, last request timestamp. Single command answers "why isn't traffic showing up?"
- Tests: cert generation (no system install in CI). `init --uninstall` must reverse what `init` installed (use a tmp `CA_DIR` to avoid touching the real system).
- Commit: `feat(ca): generate, install, and doctor the local CA`.

### Day 3 — Capture (proxy process)

**Outcome:** `upbox proxy` runs mitmproxy as the main process; every flow lands in SQLite. (Dashboard process comes Day 5; supervisor Day 5 too.)

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
- `upbox/db/store.py`: `insert_request`, `query_recent`, `export_jsonl`, `export_csv`. **Opens the DB with `PRAGMA journal_mode=WAL` and asserts it stuck.**
- `upbox/addons/capture.py`: mitmproxy addon — `response()` hook → `store.insert_request`. **Truncates `body_excerpt` at 4096 bytes before persisting.** **Wraps the hook body in a try/except so an addon exception never crashes the proxy** (per `.claude/rules/error-handling.md`).
- `upbox/proxy.py`: `run()` starts mitmproxy with the capture addon loaded. This *is* the `upbox proxy` entry point — mitmproxy stays the main event loop.
- Tests:
  - in-memory SQLite, fake mitmproxy flow → exactly 1 row, correct fields
  - `PRAGMA journal_mode` returns `wal` after store init
  - body excerpt is exactly the first 4096 bytes when input is larger
  - raising `RuntimeError` inside the capture hook does not stop the next flow from being persisted
- Commit: `feat(capture): persist every flow to SQLite (WAL + 4KB cap + addon-exception isolation)`.

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

### Day 5 — Dashboard process + supervisor

**Outcome:** `upbox dashboard` runs FastAPI/uvicorn as the main process on `127.0.0.1:8800`. `upbox start` is the supervisor that spawns `upbox proxy` and `upbox dashboard` together. Ctrl+C cleanly stops both.

- `upbox/dashboard/app.py`: FastAPI mount on `127.0.0.1:8800` only. **No in-process mitmproxy** — it's a separate process. The dashboard reads SQLite only.
- `templates/base.html`: shell with Pico.css.
- `templates/index.html`: per-tool tiles (count + bytes) + scrolling request list.
- HTMX polls `/requests/recent` every 2 seconds.
- `routes.py`: `GET /` (full page), `GET /requests/recent` (partial).
- **`upbox/supervisor.py`** (~50 lines): `upbox start` spawns `upbox proxy` and `upbox dashboard` via `subprocess.Popen`. Forwards `SIGINT` and `SIGTERM` to both. Polls every 500ms; if either dies, kill the other and exit with the dead child's status. `upbox stop` finds the running supervisor via PID file in `~/.upbox/` and sends `SIGTERM`.
- Commit: `feat(dashboard): standalone dashboard process + supervisor`.

### Day 6 — Request detail

**Outcome:** Click a row → see full headers, body excerpt, host, timing.

- `GET /requests/{id}` → `request.html` partial.
- HTMX swap into a side panel; no full reload.
- Show: tool, method, host, path, status, timing, headers (collapsible), body excerpt (first 4 KB, with toggle to load full from disk).
- Commit: `feat(dashboard): per-request detail view`.

### Day 7 — Content-aware redaction engine

**Outcome:** Configurable redactions strip secrets *before* forwarding, correctly handling JSON bodies and gzipped traffic (which is what AI APIs actually send).

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
- **`upbox/addons/redact.py` — content-aware pipeline:**
  1. Read `Content-Encoding`. Decompress if `gzip` / `br`. If unknown, skip redaction and record `redactions_applied_json: {"skipped": "encoding=<x>"}`.
  2. Read `Content-Type`. Dispatch by type:
     - `application/json` or `application/*+json`: `json.loads`, walk the structure, apply regex to every string value, re-serialise with `json.dumps`. Never touches keys, never breaks structure.
     - `text/*`: byte-level regex with JSON-safe replacement strings (no unescaped quotes).
     - Anything else (binary, multipart, octet-stream): skip with reason `{"skipped": "binary or non-text content-type"}`.
  3. Re-compress with the original encoding if any.
  4. Record what was redacted (rule name + count) in `redactions_applied_json` for the dashboard.
- Dashboard preview mode: show what *would* be redacted without enabling the rule.
- Tests:
  - **[CRITICAL]** JSON body with a secret-bearing value: redacted body is still valid JSON, original keys preserved.
  - **[CRITICAL]** gzipped JSON body: decompressed → redacted → recompressed with same encoding header; downstream decompresses successfully.
  - non-JSON binary body (image upload): skipped, `redactions_applied_json` records reason.
  - malformed JSON body: skipped gracefully, flow still forwarded (no exception).
  - combined patterns on a realistic prompt (the existing happy-path test).
- Commit: `feat(redact): content-aware redaction engine (JSON + gzip + skip-binary)`.

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
- `upbox/addons/enforce.py`: check destination; mark `blocked=1` and short-circuit if policy is `block`. **Blocked flows are still recorded by the capture addon — the audit trail must include block events.**
- Dashboard: red row for blocked, yellow for warn.
- Tests:
  - synthetic flows + allowlist permutations (happy-path).
  - a *blocked* flow still produces a SQLite row with `blocked=1` (audit trail preserved).
  - `block_unknown: warn` does not actually block the request, only flags it.
- Commit: `feat(enforce): domain allowlist per tool (audit preserved on block)`.

### Day 9 — Polish pass

**Outcome:** It feels nice. Empty states, loading states, settings.

- Empty state: "Configure your first AI tool to see traffic" → links to docs.
- Settings page: edit `redact.yaml` + `allowlist.yaml` from the UI; save back to disk.
- Live-edit reload (mitmproxy addon detects YAML mtime change and reloads rules).
- Keyboard shortcuts: `/` to search, `r` to refresh, `Esc` to close detail panel.
- Commit: `feat(dashboard): polish + live-edit rules`.

### Day 10 — Real-world test + the screenshot

**Outcome:** Run a real session. Capture the launch screenshot.

- **E2E smoke tests (must pass before manual testing):**
  - `curl --proxy http://127.0.0.1:8888 --cacert ~/.upbox/ca/upbox-ca.pem https://httpbin.org/anything` round-trips through proxy; row appears in SQLite within 2s; dashboard shows it.
  - Launch Cursor with `NODE_EXTRA_CA_CERTS=$HOME/.upbox/ca/upbox-ca.pem` on Ubuntu; trigger a Tab completion; at least one captured request visible in dashboard within 2s.
- Configure Cursor, Claude desktop / Claude Code, and ChatGPT to use the upbox proxy.
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

**Outcome:** Everything works. Launch assets ready. Supervisor proves resilient under failure.

- Run upbox for a full work day. Note every annoyance. Fix the top 3.
- **Supervisor crash-recovery test:** start `upbox start`, kill `upbox proxy` PID mid-session, verify the dashboard still serves the last captured data and the supervisor exits non-zero. Then the same with the dashboard PID — verify proxy keeps capturing and supervisor exits non-zero. (Validates the Issue 1 process-isolation decision under real failure.)
- Draft the launch X thread: screenshot + 3-line story + repo link → `launch/x-thread.md`.
- Draft the HN Show post → `launch/hn.md`.
- Draft the r/selfhosted + r/privacy crosspost → `launch/reddit.md`.
- Build the launch screenshot (real data, real story, real numbers).
- PyPI publish dry-run.
- Commit: `chore: launch assets + supervisor crash-recovery test`.

### Day 14 — Ship

**Outcome:** `v0.1.0` tagged, pushed, posted.

- Bump version to `0.1.0`; update `CHANGELOG.md`.
- `git tag v0.1.0 && git push --tags`.
- `release.yml` publishes to PyPI on tag push.
- Submit to HN Show, post the X thread, crosspost to Reddit.
- Monitor for 6+ hours; reply to every comment in the first 90 minutes.
- Commit: `release: v0.1.0`.

---

## v0.2 sprint — the compliance arc

**Target:** **1 August 2026** (eve of EU AI Act enforcement).

Same codebase. New features that unlock the second viral moment.

- **AI Act Article 26 export format.** If the EU publishes a canonical schema, conform. Otherwise ship a best-effort schema covering everything a deployer needs to log.
- **Tamper-evident hash chain** on the audit log (each row hashes the previous row's hash → any tampering breaks the chain).
- **Encrypted-at-rest SQLite** (sqlcipher or app-layer encryption — decide at the time).
- **Team mode.** Multiple endpoints reporting to one dashboard, LAN-local. Still no cloud.
- **Better Windows experience** (auto CA install).
- **Configurable retention policies** (auto-purge after N days, by tool, by host).

---

## Two-arc launch narrative

**Arc 1 — Day 14: personal paranoia angle.**

> "I just installed upbox and watched Cursor send 4,200 lines of my private repo to 3 different domains in 30 seconds. Here's the dashboard. It's open source and runs entirely on your machine."
>
> HN: *Upbox — See what your AI tools are actually sending*.

**Arc 2 — ~Day 75: compliance angle, eve of EU AI Act enforcement (1 Aug 2026).**

> "Upbox v0.2 is out. You can now export every AI request as a tamper-evident audit log mapped to EU AI Act Article 26. The deadline is tomorrow. The tool is free."
>
> HN: *Upbox v0.2 — Endpoint-level AI logging for EU AI Act Article 26*.

Two viral moments from one codebase. Arc 1 lands among devs. Arc 2 lands among security teams and compliance officers. Different audiences, different platforms, additive — not the same launch twice.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Some AI tools pin certificates and reject the local CA | Document which ones work; ship a clear "what won't work" doc. `upbox status` doctor command reports cert trust per layer so misconfiguration surfaces immediately. v0.1 covers tools that *do* work (Cursor, Copilot via VSCode, ChatGPT web, OpenAI/Anthropic API clients). |
| Linux apps don't all read the same cert store | Day 2 installs to system trust + NSS (`~/.pki/nssdb`) and prints `NODE_EXTRA_CA_CERTS` hints for Electron apps. `upbox status` checks all three layers. |
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
