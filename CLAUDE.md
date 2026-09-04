# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What upbox is

A local HTTPS proxy plus dashboard that records what AI tools (Cursor, Claude, Copilot, ChatGPT, CLI agents, browsers on web LLMs) send to the cloud, redacts secrets before forwarding, and keeps a tamper-evident audit log. MIT licensed, published on PyPI as `upbox-sh`, import package and CLI are `upbox`. Everything runs on the user's machine; upbox makes no outbound calls of its own.

Scope lives in `ROADMAP.md` (source of truth; v0.1 and v0.2 shipped, v0.3 candidates listed there). `PLAN.md` is the historical 14-day build plan behind v0.1; docstrings that mention "Day N" refer to it. When scoping work, ask which roadmap item it serves.

## Commands

```sh
uv sync --dev                                   # install runtime + dev deps
uv run pytest                                   # full suite, well under 10 s
uv run pytest tests/test_capture.py             # one file (preferred while iterating)
uv run pytest tests/test_chain.py -k truncation # one test by name
uv run ruff check . && uv run ruff format .     # lint + format (line length 100)
uv run ruff format --check .                    # what CI runs
uv run mypy upbox                               # strict mode; tests are not type-checked
uv run upbox --help                             # CLI from the checkout, no install needed
uv run upbox proxy                              # proxy alone, explicit-proxy mode, no root needed
uv run upbox dashboard                          # dashboard alone, reads ~/.upbox/upbox.db
uv run upbox start                              # supervisor: both children + OS-level capture (needs admin/root)
uv sync --group build && uv run pyinstaller packaging/upbox.spec && packaging/smoke.sh dist/upbox   # one-file binary
```

CI (`.github/workflows/ci.yml`) runs ruff check, ruff format --check, mypy, and pytest on Ubuntu, macOS, and Windows with `uv sync --dev --frozen`. If you change dependencies, run `uv lock` and commit `uv.lock`, otherwise CI fails at install.

## Architecture

Two long-running processes, one SQLite file between them. They never talk to each other directly.

```
upbox start (supervisor.py)  spawns `python -m upbox proxy` and `python -m upbox dashboard`,
                             forwards SIGINT/SIGTERM, exits when either child dies,
                             and initialises/migrates the database BEFORE spawning
   |
   |-- upbox proxy (proxy.py)      mitmproxy DumpMaster + addons, :8888, the ONLY writer
   |-- upbox dashboard (app.py)    FastAPI + Jinja2, 127.0.0.1:8800, opens the store read-only
   \-- ~/.upbox/upbox.db           SQLite in WAL mode. WAL is the IPC.
```

### Proxy request pipeline (`upbox/proxy.py`, `upbox/addons/`)

Addons are registered in this order and the order is load-bearing:

1. `FingerprintAddon` (request hook): matches `tools.yaml` rules, sets `flow.metadata["upbox_tool"]`. First match wins, so specific UA+host rules precede host-only catch-alls.
2. `EnforceAddon` (request hook): per-tool destination policy from `allowlist.yaml`. Off-allowlist hosts are tagged `flagged` (forwarded anyway) or `blocked` (synthesised 403, never reaches upstream). Only `blocked` stops egress; `flagged` means the data was sent.
3. `RedactAddon` (request hook): content-aware. JSON bodies are parsed, every string value is regex-redacted, then re-serialised; `text/*` gets byte-level regex; other content types are skipped with a logged reason. Records what it did in `flow.metadata["upbox_redactions"]`.
4. `CaptureAddon` (response hook): builds a `RequestRecord` and inserts it. Auth headers (`SENSITIVE_HEADERS`) and credential query params (`SENSITIVE_QUERY_PARAMS`) are replaced with markers before storage. These are deliberately not counted in `redactions_applied_json`, because the real value still went to the destination; that field means "upbox changed what was sent".
5. `RuleReloadWatcher` and `RetentionRunner`: asyncio tasks on mitmproxy's loop (see below).

Every addon hook body is wrapped in try/except and logs; an addon failure must never take the proxy down.

TLS scope is set at boot from two lists: `allow_hosts` is the union of hosts in `tools.yaml` (only AI destinations are decrypted; pinned-cert apps pass through), and `ignore_hosts` comes from `no_intercept.yaml` (banking, health, webmail, government, identity providers) and applies even under `--no-allowlist` or `--capture-all`. `no_intercept` is a floor: extend it, never trim it, and a broken user file falls back to the bundled defaults rather than to an empty list.

`upbox start` runs mitmproxy in LocalMode (OS-level redirect of a curated process list, `DEFAULT_CAPTURE_PROCESSES`), which needs admin/root. `upbox proxy` on its own is a regular explicit proxy for clients that set `HTTPS_PROXY`. Hostnames in LocalMode come from SNI, then the Host header, then the IP (`addons/_hostname.py`).

### Storage and the hash chain (`upbox/db/`)

`Store` is the only database API; stdlib `sqlite3`, no ORM. `schema.sql` describes a fresh database; existing databases are brought forward by numbered, idempotent migrations in `Store._migrate`, keyed on the `schema_version` table. Both paths must end at the same shape, and a test asserts it. Adding a column means a new migration step and a `SCHEMA_VERSION` bump.

Every insert is chained: `entry_hash = sha256(domain separator + canonical JSON of CHAINED_FIELDS + prev_hash)`, with the row insert and the `chain_state` head advance in one `BEGIN IMMEDIATE` transaction. The chain commits to digests of `headers_json` and `body_excerpt`, not their text, so retention can clear those columns and `upbox verify` still passes. Changing `CHAINED_FIELDS` or the serialisation invalidates every historical hash; treat it as a breaking change with a migration story. Rows written before v0.2 have `seq IS NULL` and are never backfilled.

The chain is keyless and its evidentiary value comes from a head hash that left the machine (`upbox checkpoint`). Deletions by retention are recorded in `chain_gaps` so verification resumes across them; an undisclosed gap is reported as tampering.

Single-writer rule: only the proxy process writes. The dashboard opens with `read_only=True` (`PRAGMA query_only`), never migrates an existing database, and a write attempt raises `ReadOnlyStoreError`. Retention runs inside the proxy for the same reason. Files under `~/.upbox` are forced to owner-only permissions at every open; upbox deliberately does not encrypt the database itself (see README "At rest" for the reasoning before proposing otherwise). Rows have three content states: stored, never stored by `capture.yaml` (`omitted_fields`), cleared by retention (`pruned_fields`); plus tombstones (`erased_at`). Every surface that shows a body must distinguish them.

### Rules (`upbox/rules/*.yaml` and `~/.upbox/rules/`)

Six bundled YAML files ship inside the package and are read via `importlib.resources`. A user file of the same name under `~/.upbox/rules/` overrides the bundled one.

| File | Consumed by | Editable in dashboard | Applied |
|---|---|---|---|
| `tools.yaml` | fingerprint + TLS allowlist | yes | live reload (~1 s poll) for tagging; new hosts need a restart |
| `redact.yaml` | redact | yes | live reload |
| `allowlist.yaml` | enforce | yes | live reload |
| `capture.yaml` | capture | yes | live reload |
| `no_intercept.yaml` | proxy `ignore_hosts` | no | boot only |
| `retention.yaml` | `RetentionRunner` | no | re-read on every daily pass |

Live reload keeps the previous config on a failed parse. Dashboard saves go through `settings.validate_and_write` (yaml.safe_load, shape check, atomic `os.replace`); that is the only thing the dashboard process writes.

### Dashboard (`upbox/dashboard/`)

FastAPI + Jinja2 rendering HTML partials (`/requests/recent`, `/sidebar`, `/stats`, `/requests/{id}`), with vanilla `dashboard.js` polling every 2 s and swapping fragments via `DOMParser` + `replaceChildren`. Hand-written `dashboard.css`. No HTMX, no CSS framework, no build step, no JS framework (older docs still say HTMX + Pico; the code is the truth). Autoescape is on and the templates never echo client state. Body rendering is done by Jinja filters in `app.py` (`format_body` handles JSON, NDJSON, SSE, form-encoded). The only external resource is Google Fonts, fetched by the browser.

### CLI (`upbox/cli.py`, Typer)

`init` (CA generate + install to trust stores, `--uninstall`), `start`, `proxy`, `dashboard`, `status`, `verify`, `doctor`, `prune`, `hold`, `erase`, `checkpoint`, `export --format jsonl|csv|audit`, `report`. `stop` is an unimplemented stub and `status` still prints placeholder liveness lines. `export --format audit` writes `upbox.audit.v1` (`audit_export.py`): header with ruleset digests and chain verification, one record per row, footer. Do not describe it as an "Article 26 format"; the module docstring explains why.

### CA (`upbox/ca.py`)

Self-signed root under `~/.upbox/ca/`, key at 0600, installed per platform (macOS System keychain, Linux system trust + NSS, Windows root store). Electron apps need `NODE_EXTRA_CA_CERTS`, which `upbox status` prints. The proxy writes the mitmproxy-format bundle from the same key on every start.

## Invariants

- mitmproxy is used through its addon API. Never fork it or embed it inside FastAPI.
- Proxy and dashboard stay separate processes; SQLite WAL is the only IPC. One writer.
- Dashboard binds `127.0.0.1` only. upbox makes no outbound calls beyond the proxied requests it forwards.
- Redaction runs before anything is stored or forwarded. If a flow cannot be redacted safely, drop it rather than bypass the engine.
- Never store credentials: header values, query-string keys, or bodies past the 100 KB `BODY_EXCERPT_MAX` cap. `path` is chained directly, so anything sensitive in it must be removed at capture time or never.
- `flagged` means forwarded. Never present it as blocked, in code or in copy.
- `no_intercept.yaml` is never narrowed by code changes or defaults.
- Do not add application-level database encryption; the decision and reasoning are in `atrest.py` and the README.
- Erasure is disclosed, never hidden: tombstones keep `ts`, `seq`, and both hashes; `verify`, the export, and the report count them. Never add a code path that deletes a chained row without a gap record or a tombstone.

## Conventions specific to this repo

The general rules live in `.claude/rules/` (`testing.md` and `code-quality.md` always load; `security.md` and `error-handling.md` are path-scoped to the modules listed in their frontmatter, mainly the proxy, addons, dashboard, db, and CLI). Beyond those:

- Home-relative paths are module-level constants computed at import (`fingerprint.USER_RULES_PATH`, `redact.USER_RULES_PATH`, `enforce.USER_RULES_PATH`, `settings.USER_RULES_DIR`, `store.DEFAULT_DB_PATH`, `supervisor.PID_FILE`, `ca.DEFAULT_CA_DIR`). Tests redirect them with `monkeypatch.setattr(module, "CONST", tmp_path / ...)` or pass `Store(tmp_path / "x.db")`; setting `HOME` does nothing. Never let a test touch the real `~/.upbox`.
- mitmproxy is partially untyped. Use targeted `# type: ignore[no-untyped-call]` at the call site, not blanket ignores. `mypy --strict` covers `upbox/` only.
- CI runs on Windows. Guard POSIX-only signals and paths (`SIGTERM` does not exist there; see `supervisor.py`), and keep file operations atomic with `os.replace`.
- Legal wording matters here. The EU AI Act high-risk deployer obligations were deferred by Regulation (EU) 2026/1744 to 2 December 2027 (Annex III) and 2 August 2028 (Annex I); Article 50 applies since 2 August 2026; GDPR always applied. Do not reintroduce deadline framing or claims that upbox "satisfies Article 26".
- No em-dashes (U+2014) in code, comments, docs, commit messages, or UI copy. Use commas, colons, or separate sentences.
- Changelog headings are `## vX.Y.Z (unreleased)` until release, then `## vX.Y.Z (YYYY-MM-DD)`. User-visible changes get an entry under Security, Added, Changed, Fixed, or Documentation.

## Git and release workflow

- Branch off `main`, open a PR, squash-merge. `main` is protected: PRs only, linear history, required CI on all three OSes, signed commits.
- Commits made from Claude Code sessions are SSH-signed with a key GitHub does not know, so PRs show `mergeStateStatus: BLOCKED` even when green. Verify the PR is open, not draft, mergeable, and zero commits behind `main`, then a maintainer runs `gh pr merge N --squash --admin`. GitHub signs the squash commit. Never rebase-merge (rewritten commits lose verification).
- No AI attribution in commits or PR bodies: no `Co-Authored-By: Claude`, no "Generated with" footer.
- Conventional-commit prefixes in PR titles (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `release:`).
- Native binaries: the `binaries` job in `release.yml` runs after `publish`, builds a one-file executable per platform from `packaging/upbox.spec`, runs `packaging/smoke.sh` against it, and attaches `.tar.gz`, `.dmg`, `.exe`, and `.sha256` files to the release. Build only inside the project environment (`uv sync --group build`, then `uv run pyinstaller packaging/upbox.spec`); `uv run --with pyinstaller` fails because the mitmproxy Linux hook resolves the redirector through the environment's scripts directory. A manual `workflow_dispatch` run builds and smoke-tests without publishing.
- Releases: bump `version` in `pyproject.toml` and `__version__` in `upbox/__init__.py` (they must match), date the changelog heading, update `ROADMAP.md`, merge the `release/vX.Y.Z` PR, then tag `vX.Y.Z` on `main` and push the tag. `release.yml` verifies tag == pyproject version, builds, publishes to PyPI via trusted publishing, and creates the GitHub release. PyPI versions cannot be reused, so the tag is the point of no return; confirm with the maintainer before pushing it. Full runbook: `docs/release-checklist.md` and `CONTRIBUTING.md`.

## Repo automation you will run into

`.claude/settings.json` wires hooks: `block-dangerous-commands.sh` denies pushes to `main`/`master`, force pushes, and destructive shell; `protect-files.sh` denies edits to `.env*`, keys and certificates, lock files, `.git/`, `secrets/`, and `.claude/hooks/` (use `uv lock` for the lock file); `scan-secrets.sh` and `warn-large-files.sh` guard writes; `format-on-save.sh` runs `ruff format` on edited Python. A refused edit or command is usually one of these, not a permissions bug. Local skills live in `.claude/skills/` (`ship`, `pr-review`, `debug-fix`, `tdd`, `test-writer`, `refactor`, `explain`, `context-budget`).

## Where things are documented

- `README.md`: install, quick start, "Threat model", "At rest", "Tamper evidence", EU AI Act and GDPR mapping.
- `docs/ai-act-mapping.md` (article-by-article, including GDPR Article 88 on employee monitoring), `docs/configuring-tools.md`, `docs/redaction-rules.md`, `docs/installing-ca.md`, `docs/faq.md`, `docs/release-checklist.md`.
- `docs/superpowers/specs/` and `docs/superpowers/plans/`: design specs and implementation plans for larger features (v0.1.2 live reload is the template).
- `launch/`: HN, X, and Reddit launch copy. `LICENSES/`: third-party notices.
