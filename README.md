# upbox

> See, audit, and control what your AI tools send to the cloud.

**Homepage:** <https://upbox.sh> · **Repo:** <https://github.com/krishnamallam/upbox>

**upbox** is a local-only proxy and dashboard that shows you, per tool and per request, exactly what code, files, and prompts your AI assistants ship to the cloud.

It does not send data anywhere. It does not call home. It is one binary, one SQLite database, and a small web UI that runs on your machine.

---

## The problem

When you press <kbd>Tab</kbd> in Cursor, <kbd>⌘K</kbd> in Copilot, or paste into Claude, the assumption is "just my prompt goes out." The reality is messier: the current file, neighbor files, the project tree, environment metadata, sometimes recent shell history.

Vendors aren't necessarily being shady. Their docs just don't match what people think is happening, and there's no built-in way to verify from the outside.

In 2026, the gap matters more than it did even six months ago:

- **EU AI Act enforcement.** Full obligations for high-risk AI systems take effect **2 August 2026**. Compliance asks "what is leaving the endpoint?" Most orgs have no answer.
- **Real incidents.** Source-code leaks via AI assistants are no longer hypothetical.
- **Tool sprawl.** A typical developer runs 4–8 AI tools simultaneously. No one tracks all of it.
- **Trust collapse.** A closed-source tool that watches your AI traffic is itself a privacy problem. The auditor has to be open.

## What it does

Install a local CA, point your AI tools at the upbox proxy, then watch.

- **Live feed.** Every request in real time, grouped by tool (Cursor, Claude desktop, Claude Code, Copilot, ChatGPT, Codeium, Windsurf, Gemini, Perplexity, Continue, Cody, Tabnine, …). Filter by time window, status, tool, or substring search; pin the rows you care about.
- **Inspect bodies.** Tabbed detail panel: request body, headers, fired redaction rules, allowlist verdict, and one-click export recipes (replay `curl`, JSONL dump, `upbox export`).
- **Redact before forwarding.** Regex rules strip `.env` blocks, API keys, and PII patterns *before* the request reaches the cloud.
- **Domain enforcement.** Allowlist destinations per tool. Off-allowlist requests are either **flagged** (forwarded to the cloud, but marked) or **blocked** (stopped with a 403), set per tool in `allowlist.yaml`. Flagged is not blocked: the dashboard always tells you which requests actually left.
- **Audit log.** JSON Lines + CSV export. Tamper-evident hash chain. Article-26-friendly fields.
- **Keyboard-first dashboard.** Arrow keys move through the feed, `/` jumps to search, `Esc` cascades back out, light/dark theme toggle. No mouse required.
- **Local-only.** SQLite on disk. The dashboard binds to `127.0.0.1` only. No outbound calls from upbox itself.

## Install

Pick whichever method fits your setup. All of them give you the same `upbox` command on `PATH`. Python 3.12+ is required.

> The PyPI package is named **`upbox-sh`** (the bare `upbox` name was already taken by an unrelated project). The command it installs is still **`upbox`**, so you `pipx install upbox-sh`, then run `upbox`.

### pipx *(recommended)*

`pipx` installs CLI tools into an isolated venv but keeps them on `PATH`. No conflicts with your system Python.

```sh
# Install pipx if you don't already have it
python3 -m pip install --user pipx
python3 -m pipx ensurepath

# Install upbox
pipx install upbox-sh
upbox --help
```

### uv tool

If you use [uv](https://docs.astral.sh/uv/), its built-in tool installer is faster than pipx.

```sh
uv tool install upbox-sh
upbox --help
```

### From source

For the bleeding edge or for hacking on upbox:

```sh
git clone https://github.com/krishnamallam/upbox.git
cd upbox
uv sync --dev          # drop --dev for runtime only
uv run upbox --help
```

Edits to the code take effect immediately. See [Development](#development) for test + lint commands.

Other options (uvx run-once, pip + venv, install from a tag or branch): [docs/installing.md](docs/installing.md).

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

### What gets captured

`upbox start` only redirects packets from a curated list of AI-tool processes
(`Claude`, `Cursor`, `ChatGPT`, `claude`, `codex`, `ollama`, common browsers,
etc.; see `upbox.proxy.DEFAULT_CAPTURE_PROCESSES`). VPN clients (OpenVPN,
WireGuard, Tailscale, NordVPN, Mullvad, ProtonVPN) and unrelated apps are
never touched, so tunnels stay up.

To override:

```sh
upbox start --capture-spec "claude,cursor"   # capture only these
upbox start --capture-all                    # capture every process (drops VPNs)
```

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
# open http://127.0.0.1:8800, the curl request should appear within ~2s
```

If the curl line errors with a TLS warning, your CA didn't install cleanly. Run `upbox status` to see which layer is missing and fix it (see [docs/installing-ca.md](docs/installing-ca.md)).

## Platform notes

- **macOS:** `upbox init` prompts for sudo to install into the System keychain. Cursor, Claude Desktop, VSCode, and browsers all read from it.
- **Linux:** before `upbox init`, install `libnss3-tools` (Debian / Ubuntu) or `nss-tools` (Fedora) so Firefox / Chrome / NSS-based Electron apps trust the CA too. For Node-based Electron apps (Cursor, Claude Desktop, VSCode), launch them with `NODE_EXTRA_CA_CERTS=$HOME/.upbox/ca/upbox-ca.pem`.
- **Windows:** `upbox init` writes to the per-user Trusted Root store, no admin elevation required. Firefox uses its own NSS db; import the cert manually via Settings → Privacy → Certificates → View Certificates → Authorities → Import.

Full per-platform install + uninstall walkthrough: [docs/installing-ca.md](docs/installing-ca.md).

## Uninstall

```sh
upbox init --uninstall                  # remove CA from every trust store it was installed into
rm -rf ~/.upbox/                        # remove cert, audit db, rules (optional)

# Then uninstall the package itself with whichever installer you used:
pipx uninstall upbox-sh                 # if you used pipx
uv tool uninstall upbox-sh              # if you used uv tool
~/.venvs/upbox/bin/pip uninstall upbox-sh  # if you used a venv
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
# Run the full test suite (~4s, 137 tests)
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
                  ┌───────────────────────────────────┐
                  │   upbox start  (supervisor)       │
                  │   spawns + signals both children  │
                  └────────┬────────────────┬─────────┘
                           ▼                ▼
                ┌──────────────────┐    ┌──────────────────┐
    AI tool ──▶ │  upbox proxy     │    │  upbox dashboard │ ◀── browser
                │  mitmproxy +     │    │  FastAPI + HTMX  │     127.0.0.1
                │  upbox addons    │    │  :8800           │
                │  :8888           │    └─────────┬────────┘
                └──┬───────────┬───┘              │
                   │           │                  │
            writes │           └─▶  cloud LLM     │ reads
                   ▼                              ▼
                ┌─────────────────────────────────────────┐
                │   SQLite WAL  ~/.upbox/upbox.db         │
                └─────────────────────────────────────────┘
```

`upbox start` is a supervisor: it spawns `upbox proxy` and `upbox dashboard` as separate child processes and forwards `SIGINT` / `SIGTERM` to both. If either child dies, the supervisor kills the other and exits with the dead child's status (see [`upbox/supervisor.py`](upbox/supervisor.py)).

The proxy and dashboard never talk to each other directly. They share state through SQLite running in WAL mode: the proxy writes audit rows; the dashboard reads them. SQLite WAL is the IPC. mitmproxy is the proxy core (MIT-licensed, battle-tested). FastAPI + HTMX for the dashboard: fast, no build step, no JS framework.

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

upbox is a deployer-side tool. It does not certify you compliant on its own, but it produces the *evidence and controls* compliance demands:

| Obligation | What upbox provides |
|---|---|
| **AI Act Article 4**: AI literacy (in force since Feb 2025) | A visible, inspectable record of what AI tools are doing on your endpoints. |
| **AI Act Article 26**: deployer obligations (logging, monitoring, human oversight) | Per-request audit log: timestamp, tool, destination, size, status, redactions applied. JSON Lines + CSV export. |
| **AI Act Article 50**: transparency (applies 2 Aug 2026) | Records of AI system interactions sufficient to support transparency duties toward affected persons. |
| **AI Act Article 99**: penalties | Helps demonstrate good-faith effort and concrete technical measures. |
| **GDPR Article 5**: data minimisation | Redaction engine strips PII before forwarding. |
| **GDPR Article 32**: security of processing | Technical measure providing visibility + control over data leaving the endpoint. |
| **GDPR Article 35**: DPIA | Provides concrete data flows to populate impact assessments. |

**Primary sources** (canonical ELI URLs, stable):

- AI Act full text: <https://eur-lex.europa.eu/eli/reg/2024/1689/oj>
- AI Act implementation timeline: <https://ai-act-service-desk.ec.europa.eu/en/ai-act/timeline/timeline-implementation-eu-ai-act>
- GDPR full text: <https://eur-lex.europa.eu/eli/reg/2016/679/oj>

**Article-by-article references:**

- AI Act Art. 4: <https://artificialintelligenceact.eu/article/4/>
- AI Act Art. 26: <https://artificialintelligenceact.eu/article/26/>
- AI Act Art. 50: <https://artificialintelligenceact.eu/article/50/>
- AI Act Art. 99: <https://artificialintelligenceact.eu/article/99/>
- GDPR Art. 5: <https://gdpr-info.eu/art-5-gdpr/>
- GDPR Art. 32: <https://gdpr-info.eu/art-32-gdpr/>
- GDPR Art. 35: <https://gdpr-info.eu/art-35-gdpr/>

upbox is not legal advice. Consult counsel for compliance certification.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for v0.1 → v0.3+ milestones.

## Acknowledgements

upbox stands on:

- **[mitmproxy](https://mitmproxy.org)** (MIT): the proxy core.
- **[FastAPI](https://fastapi.tiangolo.com)** (MIT): the dashboard backend.
- **[HTMX](https://htmx.org)** (BSD-2-Clause): the dashboard frontend without a build step.
- **[SQLite](https://sqlite.org)** (public domain): the audit log store.
- **[Geist](https://vercel.com/font)** and **[JetBrains Mono](https://www.jetbrains.com/lp/mono/)**: the dashboard's sans + mono typefaces.
- **[Typer](https://typer.tiangolo.com)** (MIT): the CLI.

Full third-party license texts are preserved in [`LICENSES/`](LICENSES/).

## License

upbox is licensed under the **[MIT License](LICENSE)**.

Earlier drafts of this project considered AGPL-3.0 ("the watcher must be watchable"). MIT was chosen because the audience most likely to deploy upbox at scale (security teams at companies with strict open-source policies) cannot easily adopt AGPL. The cost of that friction outweighed the philosophical win.

The auditor staying open and inspectable is preserved by the open-source commitment itself, not by a license clause. Anyone forking upbox into a closed-source product is welcome to. Their forks are not what you should trust to audit your traffic.

## Contributing

upbox is pre-1.0 and moving fast. Issues, ideas, and PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, PR conventions, and the release process.

The fastest way to help right now: install v0.1 when it ships, run it against your daily AI tools, and report what surprised you.
