# Changelog

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

## v0.1.2 — distribution polish (planned ~2 weeks post-v0.1)

- Firefox NSS auto-install on Windows.
- Live-reload of rule files (currently requires `upbox start` restart).

## v0.2 — compliance-ready (planned 2026-08-01)

- Article 26 export format (canonical EU schema if published,
  best-effort otherwise).
- Tamper-evident hash chain on the audit log.
- Encrypted-at-rest SQLite.
- Team mode (LAN-local central dashboard, multiple endpoints).
- Configurable retention.

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
