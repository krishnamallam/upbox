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

## v0.1.2: distribution polish (target: 1–2 weeks post-v0.1)

- Firefox NSS auto-install on Windows.
- Live-reload of YAML rule files (currently requires `upbox start` restart).

## v0.2 (target: 1 August 2026, eve of AI Act enforcement)

- Article 26 audit-log export format
- Tamper-evident hash chain
- Encrypted-at-rest SQLite
- Team mode (central dashboard, multiple endpoints, LAN-local)

## v0.3 and beyond

- **Native binaries:** single-file `.exe` for Windows, `.dmg` (or Homebrew formula) for macOS, AppImage for Linux. Lets non-Python users install in one click. Likely via PyInstaller; code-signing cert before shipping if antivirus false positives become a real problem.
- Plugin SDK for custom tool fingerprints
- Companion browser extension (for web LLM apps)
- macOS menu-bar app, Windows tray app
- Configurable retention policies, alerting
