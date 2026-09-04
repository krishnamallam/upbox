# Roadmap

Planned milestones for upbox. Dates are targets, not commitments. See [PLAN.md](PLAN.md) for the day-by-day build plan behind v0.1.

## v0.1 (shipped 2026-05-27)

- Local CA setup, mitmproxy bootstrap
- Tool fingerprinting (Cursor, Claude desktop, Copilot, ChatGPT, Codeium)
- Live dashboard
- Regex redaction engine
- SQLite audit log
- JSONL + CSV export

## v0.1.1 (shipped 2026-05-31)

- Dashboard pretty-prints JSON request bodies
- Request body cap raised to 100 KB (was 4 KB), with an honest truncation notice when a body exceeds it

## v0.1.2: distribution polish (live-reload shipped 2026-06-16)

- **Shipped:** Live-reload of YAML rule files. The running proxy applies edits to
  `tools.yaml`, `redact.yaml`, and `allowlist.yaml` within ~2s, no restart.
- **Shipped:** Redaction fix. Modern Anthropic (`sk-ant-api03-…`) and OpenAI
  (`sk-proj-…`) keys were leaking past the bundled patterns; now redacted, plus
  Google / Slack / GitHub fine-grained / Bearer coverage.
- **Pending:** Firefox NSS auto-install on Windows.

## v0.2: evidence you can defend (shipped 2026-09-04)

Originally scoped as the "AI Act enforcement" release for 1 August 2026.
That rationale changed on 24 July 2026, when
[Regulation (EU) 2026/1744](https://eur-lex.europa.eu/eli/reg/2026/1744/oj)
deferred the high-risk deployer obligations (Article 26 among them) to
2 December 2027 for Annex III and 2 August 2028 for Annex I. Article 50
transparency still applies from 2 August 2026, and GDPR always did.

So v0.2 is no longer a deadline release. It is about making the audit
log hold up as evidence, and about not creating legal risk for the
people who deploy it.

- **Credential redaction at capture.** `headers_json` stored `Authorization`
  and `Cookie` verbatim on every row, and `path` stored `?key=...` query
  credentials. Both fixed.
- **Tamper-evident hash chain.** Per-entry SHA-256 chain over a
  canonical serialisation, sealed checkpoints, and `upbox verify`.
  Honest about what it does not prove.
- **`upbox.audit.v1` export format.** Versioned, self-describing NDJSON
  with ruleset hashes, chain head, and an explicit coverage statement.
  Not called an "Article 26 format": Article 26(6) governs logs the
  high-risk system generates about itself, which a network observer
  cannot produce.
- **Configurable retention.** Two-tier (bodies, then whole records),
  tombstones that preserve the chain, and per-record legal hold.
- **At-rest hardening.** Restrictive file permissions plus an
  `upbox doctor` that reports real full-disk-encryption status.
  Deliberately **not** application-level encryption: on an unattended
  daemon the key ends up next to the database, which is theatre.
- **TLS-interception exclusion list.** Default passthrough for banking,
  health, webmail, and government destinations, as a proportionality
  control for workplace deployments.

Moved out of v0.2:

- **Encrypted-at-rest SQLite.** Cut. See at-rest hardening above.
- **Team mode.** Deferred to v0.3. A LAN-exposed central dashboard
  contradicts the `127.0.0.1`-only rule and multiplies the
  employee-monitoring exposure. It needs the workplace-deployment
  groundwork first.

## v0.3: subject rights (shipped 2026-09-04)

- **Shipped:** metadata-only mode (`capture.yaml`), the
  subject-transparency report (`upbox report`, `/transparency`), and
  chain-preserving per-record erasure (`upbox erase`).

## v0.4: native binaries (shipped 2026-09-04)

- **Shipped:** one-file `upbox` executables for Windows x86_64 (`.exe`), macOS Apple Silicon (`.dmg`), and Linux x86_64 (`.tar.gz`), built and smoke-tested in the release workflow. Unsigned; a code-signing certificate follows if antivirus false positives become a real problem.

## Later

- **Workplace deployment pack:** worker notice template, DPIA skeleton
  keyed to upbox's actual data flows, works-council checklist. Blocks
  team mode.
- **Team mode** (central dashboard, multiple endpoints, LAN-local),
  moved from v0.2 and gated behind the deployment pack.
- Plugin SDK for custom tool fingerprints
- Companion browser extension (for web LLM apps)
- macOS menu-bar app, Windows tray app
- Alerting
