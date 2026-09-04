# Changelog

## v0.4.0 (unreleased)

### Added

- **Native binaries.** Every release now ships one-file executables built by
  PyInstaller on GitHub's runners: `upbox-<version>-windows-x86_64.exe`,
  `upbox-<version>-macos-arm64.dmg` (a disk image holding the `upbox` binary
  and a README), and `upbox-<version>-linux-x86_64.tar.gz`, each with a
  `.sha256` beside it. No Python needed. Same CLI as the PyPI package,
  mitmproxy's local-mode redirectors bundled. Each binary is smoke-tested on
  its own platform before it is attached to the release. Unsigned for now;
  `docs/installing.md` has the Gatekeeper and SmartScreen steps and the
  checksum commands.

### Changed

- `upbox start` spawns its proxy and dashboard children correctly when running
  from a frozen binary, where `sys.executable` is upbox itself rather than a
  Python interpreter.

### Internal

- `uv sync --group build` installs PyInstaller. `packaging/upbox.spec` is the
  build input, `packaging/smoke.sh` the acceptance test, and the release
  workflow's new `binaries` job runs both on three platforms after the PyPI
  publish. A manual `workflow_dispatch` run builds and tests without
  publishing.
- The release workflow attaches only the wheel and sdist, not the
  `.gitignore` that `uv build` leaves in `dist/`.

## v0.3.0 (2026-09-04)

The subject-rights release. Store less, show what is stored, erase on request,
all without weakening the hash chain.

### Added

- **Metadata-only capture.** A sixth rule file, `~/.upbox/rules/capture.yaml`,
  with `bodies` and `headers` booleans. Both `false` stores timestamps, tools,
  hosts, paths, sizes, status, hashes, and outcomes, and nothing else: the
  recommended configuration on machines you do not own. Live-reloaded, editable
  from the dashboard settings page, and disclosed in every audit export
  (`ruleset.capture_sha256`, per-record `capture.omitted_fields`). A user file
  that fails to parse puts upbox in metadata-only mode rather than storing more
  than intended.
- **`upbox erase`.** Per-record erasure for GDPR Article 17. Select by `--id`,
  `--host`, `--tool`, or a time range, give a `--reason`, preview with
  `--dry-run`. Erased rows become tombstones: every content column is cleared
  and only the timestamp, `seq`, and hashes survive, so `upbox verify` still
  passes and reports `N entries erased on request`. A legal hold on any
  selected row refuses the whole operation. Tombstones appear in the audit
  export with `erased.at` and `erased.reason`, and never in the dashboard feed.
- **`upbox report`** and the dashboard `/transparency` page. What upbox holds
  about this machine's user, for GDPR Article 15 access requests: categories
  of data and whether each is stored, recipients per tool and host, retention
  in force, erasures, chain status, how to get a copy or erase, and the
  limitations. `--records` writes the machine-readable `upbox.audit.v1` copy
  alongside. One generator feeds both the Markdown and the page.

### Changed

- The dashboard Body and Headers tabs distinguish "not stored by policy" from
  "cleared by retention" from "empty". A `capture: metadata-only` badge shows
  when both content columns are off.
- `upbox prune` no longer counts or stamps rows that hold no content.
- `upbox doctor` prints the capture policy in force.
- The dashboard settings page no longer tells you to restart after an edit;
  rules have live-reloaded since v0.1.2.

### Upgrading

- Nothing to do. The first writer to open the database (`upbox start`, or any
  command except `dashboard`) adds three nullable columns; no data is
  rewritten and every existing hash still verifies. `upbox dashboard` on its
  own never migrates and will show a one-line notice until you run
  `upbox start` once.

### Documentation

- README: metadata-only mode, subject rights, and the erasure trust model in
  the tamper-evidence section.
- `docs/ai-act-mapping.md`: GDPR Article 15 and Article 17 sections.

## v0.2.0 (2026-09-04)

The compliance release, reshaped. v0.2 was scoped as the "AI Act enforcement"
release for 1 August 2026. On 24 July 2026,
[Regulation (EU) 2026/1744](https://eur-lex.europa.eu/eli/reg/2026/1744/oj)
(the Digital Omnibus on AI) amended Article 113 and deferred Chapter III
Sections 1 to 3, so the deployer obligations this project was pinned to now
apply from 2 December 2027 (Annex III) and 2 August 2028 (Annex I). Article 50
transparency did start on 2 August 2026, and GDPR always applied.

So this release is about making the audit log hold up as evidence, and about not
creating legal risk for the people who deploy it.

A note on v0.1.2: it was merged on 2026-06-30 but never tagged or published, so
PyPI went from 0.1.1 straight to 0.2.0. The live-reload and the Anthropic/OpenAI
key redaction fix listed under v0.1.2 below reach PyPI users for the first time
in this release. If you installed from PyPI you are on 0.1.1 and should upgrade.

### Security

- **Auth-bearing headers are no longer stored.** `headers_json` kept
  `Authorization`, `Cookie`, and `x-api-key` values verbatim on every row, so
  every authenticated request wrote a live credential into the audit database.
  Values are now replaced with `[REDACTED:header]`; the header name is kept,
  since carrying a credential is itself worth recording. **If you have been
  running upbox, rotate any keys used through it and delete the old database.**
  This is deliberately not counted in `redactions_applied_json`, which means
  "upbox changed what was sent": the real value still went to the destination.
- **Credentials in the URL query string are no longer stored.** `path` is
  recorded with the query attached, and Google (among others) accepts an API key
  there, so `?key=...` was written verbatim. Worse than the header case: `path`
  is chained directly rather than via a digest, so retention could never clear
  it afterwards. Values for known credential parameters (`key`, `api_key`,
  `access_token`, `token`, `client_secret`, and similar) are now replaced with
  `[REDACTED:query]` at capture. The rotate-and-delete advice above applies to
  these too.
- **Owner-only permissions** (`0700` on `~/.upbox`, `0600` on the database and
  its `-wal`/`-shm`) are enforced at every open.
- **The dashboard no longer writes to the database.** It opens read-only, and no
  longer runs schema migrations on your data from the reader process. `upbox
  start` initialises the database once, before either child starts.

### Added

- **Tamper-evident hash chain.** Each row carries a SHA-256 over its own fields
  plus the previous row's hash. `upbox verify` recomputes the chain and reports
  OK, BROKEN at a seq, or empty, with exit codes 0 and 1. `upbox checkpoint`
  seals the current head so it can leave the machine.
- **`upbox.audit.v1` export format**, via `upbox export --format audit`.
  Newline-delimited JSON carrying ruleset digests, the chain verification
  result, retention disclosures, a coverage statement, and per-record notes.
  `jsonl` and `csv` are unchanged.
- **Configurable retention** in `~/.upbox/rules/retention.yaml`. `body_days`
  (default 7) clears stored bodies and headers while keeping the chain
  verifying; `record_days` (default null) deletes rows and records a chain gap
  so verification can resume across it. Plus `upbox prune`, `upbox hold` for
  legal holds, and a daily pass in the proxy.
- **`upbox doctor`**, reporting volume-encryption status per platform, database
  file modes, and chain health. It reports UNKNOWN rather than guessing.
- **TLS-interception exclusion list** (`no_intercept.yaml`). Banking, health,
  private webmail, government, and identity-provider destinations are never
  decrypted, regardless of the allowlist or `--capture-all`.
- A `schema_version` table with numbered migrations, replacing the ad-hoc
  add-a-column pattern.

### Changed

- **Encrypted-at-rest SQLite was cut**, not deferred. On an unattended daemon
  the key ends up next to the database, which defeats `strings` and nothing
  else while licensing a false README claim. upbox now documents full-disk
  encryption and reports whether it is on. See the "At rest" section of the
  README for the full reasoning.
- **Team mode moved to v0.3**, behind the workplace-deployment groundwork.
- The "Article 26 export format" on the roadmap became `upbox.audit.v1`.
  Article 26(6) covers logs the high-risk AI system generates about itself;
  upbox observes the network from outside the system and cannot produce those.

### Documentation

- Corrected the AI Act dates across `README.md` and `docs/ai-act-mapping.md`,
  which claimed full high-risk obligations took effect 2 August 2026.
- Added a GDPR Article 88 section: intercepting TLS on employee devices is
  employee monitoring, and in some Member States (Italy, via Art. 4 of Law
  300/1970) it needs a union agreement or Labour Inspectorate authorisation.
- New README sections: "At rest" and "Tamper evidence", both stating plainly
  what upbox does not protect against.
- Noted that `docs/ai-act-mapping.md` had documented a `blocked` column renamed
  to `enforcement` back in v0.1.0.

## v0.1.2 (never published, folded into v0.2.0)

Live-reload of rule files and a redaction-leak fix.

### Added

- The running proxy now **reloads rule files in place**. Editing `tools.yaml`,
  `redact.yaml`, or `allowlist.yaml` (via the dashboard or by hand) applies within
  ~2s — no `upbox start` restart. A failed edit (bad YAML or uncompilable regex)
  keeps the previously-loaded config and is logged; it never crashes the proxy or
  blanks the rules. Adding a brand-new intercepted host still needs a restart
  (the TLS `allow_hosts` set is fixed at boot).
- Redaction coverage for Google API keys, Slack tokens, GitHub fine-grained and
  server tokens, and generic `Bearer <token>` values appearing in request bodies.

### Fixed

- **Anthropic and OpenAI API keys were leaking unredacted.** The bundled patterns
  predate base64url key formats, so real modern keys (`sk-ant-api03-…` with `_`,
  `sk-proj-…` / `sk-svcacct-…`) did not match and were forwarded to the cloud.
  Patterns now tolerate `-`/`_` and the modern prefixes; `anthropic-key` is ordered
  before `openai-key` so keys are labelled correctly.

### Changed

- Rule writes from the dashboard are now atomic (`os.replace`), so the watcher
  never reads a half-written file. The save confirmation notes the change applies
  automatically.

## v0.1.1 (2026-05-31)

Dashboard readability and a larger body cap, plus a docs restructuring.

### Changed

- Request bodies are now stored up to **100 KB** (was 4 KB). `body_hash`
  (SHA-256 of the full body) and `req_bytes` (true size) are unchanged, so
  integrity and real-size reporting still hold. The 4 KB value was a
  database-size heuristic, not a compliance floor; 100 KB captures typical
  prompt and telemetry payloads whole for the Article 26 "what was sent"
  record while still bounding growth. Adjust `BODY_EXCERPT_MAX` in
  `upbox/db/store.py` for a different ceiling.
- The dashboard **pretty-prints JSON request bodies** instead of rendering one
  compact line. Redaction markers stay highlighted in the formatted output.
  Non-JSON or truncated bodies are shown verbatim.

### Added

- Body tab shows a "first 100 KB of N" notice when a request body exceeds the
  cap, instead of silently cutting it off.

### Documentation

- Architecture diagram corrected to show the supervisor plus the separate
  proxy and dashboard processes, with SQLite WAL as the IPC.
- Roadmap moved to `ROADMAP.md`; added `CONTRIBUTING.md` (dev setup, PR
  conventions, release process). README trimmed: dropped badges and marketing
  voice, collapsed install methods to three with the rest in
  `docs/installing.md`.

### Internal

- Release workflow grants `contents: write` and uses `skip-existing` so a
  re-run does not fail on an already-published file.

## v0.1.0 — 2026-05-27

Initial public release. Single-machine AI tool traffic auditor: local
proxy, dashboard, redaction, per-tool allowlist, audit-log export.
Supports macOS, Linux, and Windows.

### Added

- **CA management** — `upbox init` generates a local RSA-2048 CA and
  installs to platform trust stores: macOS System keychain; Linux
  system trust + NSS + `NODE_EXTRA_CA_CERTS` hints; Windows per-user
  Trusted Root store via `certutil -user -addstore` (no admin
  required). `upbox init --uninstall` reverses every layer.
  `upbox status` reports trust per layer.
- **Capture** — mitmproxy-based proxy persists every flow to SQLite
  (WAL mode). Body excerpt capped at 4 KB; `body_hash` records SHA-256
  of the full body. `upbox start` redirects only a curated list of
  AI-tool processes (`upbox.proxy.DEFAULT_CAPTURE_PROCESSES`: Claude,
  Cursor, ChatGPT, Windsurf, Codex, Ollama, common browsers, …), so VPN
  clients (OpenVPN, WireGuard, Tailscale, NordVPN, Mullvad, ProtonVPN)
  and unrelated apps keep their tunnels up; `--capture-all` opts back
  into the catch-all. A TLS allowlist derived from `tools.yaml` decrypts
  only AI hosts — pinned-cert apps (banking, Teams, Outlook) pass
  through untouched.
- **Fingerprinting** — 15 bundled rules covering Cursor, Claude
  Desktop, Claude Code, GitHub Copilot, ChatGPT, Windsurf, Codeium,
  Continue, Cody, Perplexity, Tabnine, and Replit AI, plus generic
  OpenAI / Anthropic / Gemini API fallbacks. The union of their `hosts`
  forms the TLS allowlist.
- **Redaction** — content-aware. JSON bodies are parsed, walked, and
  re-serialised so structure is preserved. Text bodies get byte regex.
  Binary bodies are skipped with a logged reason. gzip / brotli
  encodings are handled transparently via mitmproxy. Defaults catch
  AWS, OpenAI, Anthropic, GitHub keys and dotenv lines.
- **Enforce** — per-tool destination allowlist. A host off a tool's
  allowlist is recorded in the audit log's `enforcement` field: the
  `warn` policy tags it **flagged** and still forwards it to the cloud;
  the `block` policy tags it **blocked** and short-circuits with HTTP
  403 so it never leaves the machine. The dashboard shows the two
  distinctly — flagged is forwarded, not blocked.
- **Dashboard** — FastAPI on `127.0.0.1:8800` only (refuses to bind
  elsewhere). Live feed grouped by tool, a filter bar (time range /
  status / tool / full-text search), and a tabbed detail panel (Body /
  Headers / Redactions / Allowlist / Export) with one-click export
  recipes. Keyboard-first (arrow keys to move, `/` to search, `Esc` to
  clear) with a light/dark theme toggle. Server-rendered HTMX partials,
  custom token CSS (Geist + JetBrains Mono); no build step.
- **Settings page** — edit `tools.yaml`, `redact.yaml`,
  `allowlist.yaml` from the dashboard with `yaml.safe_load`
  validation. Writes to `~/.upbox/rules/`.
- **Supervisor** — `upbox start` spawns `upbox proxy` and `upbox
  dashboard` as separate processes (per eng-review process model
  decision). Forwards signals; exits with the dead child's rc if
  either dies.
- **Export** — `upbox export --format jsonl|csv [--since TS --until
  TS --tool NAME] [-o FILE]`.
- **Docs** — installing-ca, configuring-tools, redaction-rules,
  ai-act-mapping, faq.
- **Launch assets** — X thread, HN Show post, Reddit posts ready in
  `launch/`.

### Tests

137 tests covering: CA generation + per-platform install / uninstall
(subprocess monkeypatched), WAL pragma assertion, body excerpt 4 KB cap,
addon exception isolation (capture, fingerprint, redact), all four
critical redaction tests from the eng-review (JSON, gzip, binary skip,
malformed JSON), the curated capture default (regression guard that it
never lists a VPN client), per-tool allowlist policy with the
flagged/blocked split, the `blocked`→`enforcement` schema migration,
dashboard routes + filter/tab rendering, and supervisor child-death
handling.

## v0.3 and beyond (planned)

- **Native binaries** distributed via GitHub Releases:
  - Windows: single-file `upbox.exe` (PyInstaller, ~50 MB, no
    Python needed on the host).
  - macOS: signed `.dmg` or Homebrew tap formula.
  - Linux: AppImage (universal across distros).

  Deferred because: (a) mitmproxy + PyInstaller has known footguns that
  take iteration to get right, and (b) unsigned PyInstaller binaries hit
  Windows Defender's heuristic on roughly 1 in 5 machines, which needs a
  $300/yr code-signing cert that's better acquired calmly than under
  launch pressure.
