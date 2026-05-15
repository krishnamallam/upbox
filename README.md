# upbox

> See, audit, and control what your AI tools send to the cloud.

**Homepage:** <https://upbox.sh> · **Repo:** <https://github.com/krishnamallam/upbox>

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Status: pre-release](https://img.shields.io/badge/status-pre--release-orange.svg)](#roadmap)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](#)
[![Platforms](https://img.shields.io/badge/platforms-linux%20%7C%20macos%20%7C%20windows-lightgrey.svg)](#)

**upbox** is a local-only proxy and dashboard that shows you, per tool and per request, exactly what code, files, and prompts your AI assistants ship to the cloud.

It does not send data anywhere. It does not call home. It is one binary, one SQLite database, and a small web UI that runs on your machine.

---

## The problem

When you press <kbd>Tab</kbd> in Cursor, <kbd>⌘K</kbd> in Copilot, or paste into Claude, the assumption is "just my prompt goes out." The reality is messier: the current file, neighbor files, the project tree, environment metadata, sometimes recent shell history.

Vendors aren't necessarily being shady. Their docs just don't match what people think is happening, and there's no built-in way to verify from the outside.

In 2026, the gap matters more than it did even six months ago:

- **EU AI Act enforcement.** Full obligations for high-risk AI systems take effect **2 August 2026**. Compliance asks "what is leaving the endpoint?" — most orgs have no answer.
- **Real incidents.** Source-code leaks via AI assistants are no longer hypothetical.
- **Tool sprawl.** A typical developer runs 4–8 AI tools simultaneously. No one tracks all of it.
- **Trust collapse.** A closed-source tool that watches your AI traffic is itself a privacy problem. The auditor has to be open.

## What it does

Install a local CA, point your AI tools at the upbox proxy, then watch.

- **Live feed.** Every request in real time, grouped by tool (Cursor, Claude desktop, Copilot, ChatGPT, Codeium, …).
- **Inspect bodies.** The actual prompt, the actual file content, the actual headers.
- **Redact before forwarding.** Regex rules strip `.env` blocks, API keys, and PII patterns *before* the request reaches the cloud.
- **Domain enforcement.** Allowlist destinations per tool. Block or warn on unknown hosts. See the receipts.
- **Audit log.** JSON Lines + CSV export. Tamper-evident hash chain. Article-26-friendly fields.
- **Local-only.** SQLite on disk. The dashboard binds to `127.0.0.1` only. No outbound calls from upbox itself.

## Install

Pick whichever method fits your setup. All of them give you the same `upbox` command on `PATH`. Python 3.12+ is required.

### Method 1 — pipx *(recommended for most users)*

`pipx` installs CLI tools into an isolated venv but keeps them on `PATH`. No conflicts with your system Python or other projects.

```sh
# Install pipx if you don't already have it
python3 -m pip install --user pipx
python3 -m pipx ensurepath

# Install upbox
pipx install upbox

# Verify
upbox --help
```

### Method 2 — uv tool

If you use [uv](https://docs.astral.sh/uv/) (Astral's Python toolchain), it has a built-in tool installer that's faster than pipx.

```sh
uv tool install upbox
upbox --help
```

### Method 3 — uvx *(no install, run once)*

Run upbox without installing anything globally. uv resolves and caches deps the first time, then it's instant.

```sh
uvx upbox --help
uvx upbox init
uvx upbox start
```

Good for one-shot smoke tests; less good as a daily driver because each command re-resolves.

### Method 4 — pip + venv *(no extra tools)*

```sh
python3 -m venv ~/.venvs/upbox
~/.venvs/upbox/bin/pip install upbox
~/.venvs/upbox/bin/upbox --help

# Optional: symlink to PATH
ln -s ~/.venvs/upbox/bin/upbox ~/.local/bin/upbox
```

On Ubuntu 24+, Debian 12+, and recent Fedora, system `pip install` is blocked by [PEP 668](https://peps.python.org/pep-0668/). Use a venv (above) or one of methods 1–3.

### Method 5 — From source *(latest `main`)*

For the bleeding edge or for development:

```sh
git clone https://github.com/krishnamallam/upbox.git
cd upbox
uv sync                      # installs runtime + dev deps from uv.lock
uv run upbox --help
```

### Method 6 — Install from a tag or branch directly

```sh
# Latest tagged release
pipx install git+https://github.com/krishnamallam/upbox.git@v0.1.0

# Latest main
pipx install git+https://github.com/krishnamallam/upbox.git@main

# Or via pip/venv
pip install git+https://github.com/krishnamallam/upbox.git@v0.1.0
```

### Method 7 — Editable install *(hacking on upbox)*

```sh
git clone https://github.com/krishnamallam/upbox.git
cd upbox
uv sync --dev                # adds pytest, ruff, mypy, httpx
uv run upbox --help          # runs your local checkout
```

Edits to the code take effect immediately. See [Development](#development) for the test + lint commands.

## Quick start

After install, three commands get you running:

```sh
upbox init        # one-time: generates + installs the local CA
upbox start       # boots proxy on :8888 and dashboard on :8800
# Ctrl+C to stop both.
```

Then:

1. Point an AI tool at `http://127.0.0.1:8888` (or set `HTTPS_PROXY=http://127.0.0.1:8888`).
2. Open the dashboard at `http://127.0.0.1:8800`.

Per-tool setup recipes (Cursor, Claude desktop / Code, GitHub Copilot, ChatGPT, curl, SDK clients): [docs/configuring-tools.md](docs/configuring-tools.md).

## Verify the install

These should all succeed:

```sh
upbox --help                            # CLI lists: init, start, proxy, dashboard, stop, status, export
upbox status                            # reports CA trust per layer for your platform
```

End-to-end smoke test (after `upbox init`):

```sh
# Terminal 1
upbox proxy

# Terminal 2
curl --proxy http://127.0.0.1:8888 \
     --cacert ~/.upbox/ca/upbox-ca.pem \
     https://httpbin.org/anything

# Terminal 3
upbox dashboard
# open http://127.0.0.1:8800 — the curl request should appear within ~2s
```

If the curl line errors with a TLS warning, your CA didn't install cleanly — run `upbox status` to see which layer is missing and fix it (see [docs/installing-ca.md](docs/installing-ca.md)).

## Platform notes

- **macOS** — `upbox init` prompts for sudo to install into the System keychain. Cursor, Claude Desktop, VSCode, and browsers all read from it.
- **Linux** — before `upbox init`, install `libnss3-tools` (Debian / Ubuntu) or `nss-tools` (Fedora) so Firefox / Chrome / NSS-based Electron apps trust the CA too. For Node-based Electron apps (Cursor, Claude Desktop, VSCode), launch them with `NODE_EXTRA_CA_CERTS=$HOME/.upbox/ca/upbox-ca.pem`.
- **Windows** — `upbox init` writes to the per-user Trusted Root store, no admin elevation required. Firefox uses its own NSS db; import the cert manually via Settings → Privacy → Certificates → View Certificates → Authorities → Import.

Full per-platform install + uninstall walkthrough: [docs/installing-ca.md](docs/installing-ca.md).

## Uninstall

```sh
upbox init --uninstall                  # remove CA from every trust store it was installed into
rm -rf ~/.upbox/                        # remove cert, audit db, rules (optional)

# Then uninstall the package itself with whichever installer you used:
pipx uninstall upbox                    # if you used pipx
uv tool uninstall upbox                 # if you used uv tool
~/.venvs/upbox/bin/pip uninstall upbox  # if you used a venv
```

## Development

Clone + install dev deps:

```sh
git clone https://github.com/krishnamallam/upbox.git
cd upbox
uv sync --dev
```

Then:

```sh
# Run the full test suite (~2s, 85 tests)
uv run pytest -v

# Run a single test file
uv run pytest tests/test_capture.py -v

# Lint + format
uv run ruff check .
uv run ruff format .

# Type check
uv run mypy upbox

# Run upbox from your checkout (no install needed)
uv run upbox --help
uv run upbox status
uv run upbox proxy
```

CI runs the same on `ubuntu-latest`, `macos-latest`, and `windows-latest`. The full 14-day build plan and the architectural decisions behind it live in [PLAN.md](PLAN.md).

## Architecture

```
                 ┌──────────────────┐
   AI tool  ───▶ │  mitmproxy core  │ ───▶  cloud LLM
                 │  + upbox addons  │
                 └────────┬─────────┘
                          ▼
                  ┌───────────────┐       ┌──────────────────┐
                  │  SQLite       │ ◀──── │  Dashboard       │
                  │  audit log    │       │  (FastAPI + HTMX)│
                  └───────────────┘       └──────────────────┘
```

Single Python process. mitmproxy as the proxy core (MIT-licensed, battle-tested). SQLite as the audit store. FastAPI + HTMX for the dashboard — fast, no build step, no JS framework.

## Threat model

**What upbox protects against**
- Surprise data egress from AI tools you already trust.
- Accidentally pasting `.env` contents or API keys into a cloud LLM.
- Compliance gaps where you need to answer "what did our laptops send to AI providers last month?"

**What upbox does not protect against**
- Tools that pin certificates and reject the local CA (some won't work without bypasses).
- Malicious local processes that read files directly without going through your tools.
- Data already exfiltrated before installation.

**What upbox itself does**
- Reads your AI traffic via a local CA you install (and can uninstall).
- Stores audit data in `~/.upbox/upbox.db` (SQLite; encrypted-at-rest planned for v0.2).
- Serves the dashboard on `127.0.0.1` only.
- Never makes outbound network calls of its own.

## EU AI Act and GDPR mapping

upbox is a deployer-side tool. It does not certify you compliant on its own — but it produces the *evidence and controls* compliance demands:

| Obligation | What upbox provides |
|---|---|
| **AI Act Article 4** — AI literacy (in force since Feb 2025) | A visible, inspectable record of what AI tools are doing on your endpoints. Real artefacts beat policy slides. |
| **AI Act Article 26** — deployer obligations (logging, monitoring, human oversight) | Per-request audit log: timestamp, tool, destination, size, status, redactions applied. JSON Lines + CSV export. |
| **AI Act Article 50** — transparency (applies 2 Aug 2026) | Records of AI system interactions sufficient to support transparency duties toward affected persons. |
| **AI Act Article 99** — penalties | Helps demonstrate good-faith effort and concrete technical measures. |
| **GDPR Article 5** — data minimisation | Redaction engine strips PII before forwarding. |
| **GDPR Article 32** — security of processing | Technical measure providing visibility + control over data leaving the endpoint. |
| **GDPR Article 35** — DPIA | Provides concrete data flows to populate impact assessments. |

**Primary sources** (canonical ELI URLs — stable):

- AI Act full text: <https://eur-lex.europa.eu/eli/reg/2024/1689/oj>
- AI Act implementation timeline: <https://ai-act-service-desk.ec.europa.eu/en/ai-act/timeline/timeline-implementation-eu-ai-act>
- GDPR full text: <https://eur-lex.europa.eu/eli/reg/2016/679/oj>

**Article-by-article references:**

- AI Act Art. 4 — <https://artificialintelligenceact.eu/article/4/>
- AI Act Art. 26 — <https://artificialintelligenceact.eu/article/26/>
- AI Act Art. 50 — <https://artificialintelligenceact.eu/article/50/>
- AI Act Art. 99 — <https://artificialintelligenceact.eu/article/99/>
- GDPR Art. 5 — <https://gdpr-info.eu/art-5-gdpr/>
- GDPR Art. 32 — <https://gdpr-info.eu/art-32-gdpr/>
- GDPR Art. 35 — <https://gdpr-info.eu/art-35-gdpr/>

upbox is not legal advice. Consult counsel for compliance certification.

## Roadmap

**v0.1 — "first viral screenshot"** (target: 15 July 2026)

- Local CA setup, mitmproxy bootstrap
- Tool fingerprinting (Cursor, Claude desktop, Copilot, ChatGPT, Codeium)
- Live dashboard
- Regex redaction engine
- SQLite audit log
- JSONL + CSV export

**v0.2 — "compliance-ready"** (target: 1 August 2026 — eve of AI Act enforcement)

- Article 26 audit-log export format
- Tamper-evident hash chain
- Encrypted-at-rest SQLite
- Team mode (central dashboard, multiple endpoints, LAN-local)

**v0.3 and beyond**

- Plugin SDK for custom tool fingerprints
- Companion browser extension (for web LLM apps)
- macOS menu-bar app, Windows tray app
- Configurable retention policies, alerting

## Acknowledgements

upbox stands on:

- **[mitmproxy](https://mitmproxy.org)** (MIT) — the proxy core. Without it this project would take a year, not two weeks.
- **[FastAPI](https://fastapi.tiangolo.com)** (MIT) — the dashboard backend.
- **[HTMX](https://htmx.org)** (BSD-2-Clause) — the dashboard frontend without a build step.
- **[SQLite](https://sqlite.org)** (public domain) — the audit log store.
- **[Pico.css](https://picocss.com)** (MIT) — minimal CSS for the dashboard.
- **[Typer](https://typer.tiangolo.com)** (MIT) — the CLI.

Full third-party license texts are preserved in [`LICENSES/`](LICENSES/).

## License

upbox is licensed under the **[MIT License](LICENSE)**.

Earlier drafts of this project considered AGPL-3.0 ("the watcher must be watchable"). MIT was chosen because the audience most likely to deploy upbox at scale — security teams at companies with strict open-source policies — cannot easily adopt AGPL. The cost of that friction outweighed the philosophical win.

The auditor staying open and inspectable is preserved by the open-source commitment itself, not by a license clause. Anyone forking upbox into a closed-source product is welcome to. Their forks are not what you should trust to audit your traffic. Trust this repository, or trust no one.

## Contributing

upbox is pre-1.0 and moving fast. Issues, ideas, and PRs welcome.

The fastest way to help right now: install v0.1 when it ships, run it against your daily AI tools, and report what surprised you. The launch screenshot is the marketing campaign — yours might be the one that ships.
