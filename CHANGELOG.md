# Changelog

## v0.1.0 — 2026-05-15

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
  of the full body.
- **Fingerprinting** — 9 bundled rules covering Cursor, Claude
  desktop, Claude Code, GitHub Copilot, ChatGPT, Codeium, plus generic
  OpenAI / Anthropic / Gemini API fallbacks.
- **Redaction** — content-aware. JSON bodies are parsed, walked, and
  re-serialised so structure is preserved. Text bodies get byte regex.
  Binary bodies are skipped with a logged reason. gzip / brotli
  encodings are handled transparently via mitmproxy. Defaults catch
  AWS, OpenAI, Anthropic, GitHub keys and dotenv lines.
- **Enforce** — per-tool destination allowlist. `warn` flags the
  request and still forwards; `block` short-circuits with HTTP 403.
  Either way the audit log records the decision.
- **Dashboard** — FastAPI on `127.0.0.1:8800` only (refuses to bind
  elsewhere). Per-tool tiles, live feed, click-through detail
  (collapsible headers + body excerpt). Vanilla CSS + JS; no build
  step.
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

80+ unit tests covering: CA generation + per-platform install /
uninstall (subprocess monkeypatched), WAL pragma assertion, body
excerpt 4 KB cap, addon exception isolation (capture, fingerprint,
redact), all four critical redaction tests from the eng-review (JSON,
gzip, binary skip, malformed JSON), per-tool allowlist policy,
dashboard route smoke, supervisor child-death handling.

## v0.2 — compliance-ready (planned 2026-08-01)

- Article 26 export format (canonical EU schema if published,
  best-effort otherwise).
- Tamper-evident hash chain on the audit log.
- Encrypted-at-rest SQLite.
- Team mode (LAN-local central dashboard, multiple endpoints).
- Configurable retention.
- Live-reload of rule files (currently requires restart).
- Firefox NSS install on Windows (currently manual).
