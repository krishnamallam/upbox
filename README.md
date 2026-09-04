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

- **EU AI Act.** Transparency duties (Article 50) start applying **2 August 2026**. The high-risk deployer duties, Article 26 among them, were pushed back to **2 December 2027** (Annex III) and **2 August 2028** (Annex I) by [Regulation (EU) 2026/1744](https://eur-lex.europa.eu/eli/reg/2026/1744/oj/eng), the Digital Omnibus on AI. The deadline moved; the question did not. Compliance still asks "what is leaving the endpoint?" and most orgs have no answer.
- **Real incidents.** Source-code leaks via AI assistants are no longer hypothetical.
- **Tool sprawl.** A typical developer runs 4–8 AI tools simultaneously. No one tracks all of it.
- **Trust collapse.** A closed-source tool that watches your AI traffic is itself a privacy problem. The auditor has to be open.

## What it does

Install a local CA, point your AI tools at the upbox proxy, then watch.

- **Live feed.** Every request in real time, grouped by tool (Cursor, Claude desktop, Claude Code, Copilot, ChatGPT, Codeium, Windsurf, Gemini, Perplexity, Continue, Cody, Tabnine, …). Filter by time window, status, tool, or substring search; pin the rows you care about.
- **Inspect bodies.** Tabbed detail panel: request body (JSON pretty-printed), headers, fired redaction rules, allowlist verdict, and one-click export recipes (replay `curl`, JSONL dump, `upbox export`).
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

Banking, health, private webmail, government, and identity-provider
destinations are **never decrypted**, even under `--capture-all`. That list
lives in `~/.upbox/rules/no_intercept.yaml` and is meant to be extended, not
trimmed. See "Deploying on machines you don't own" below.

### Audit commands

```sh
upbox verify                       # recompute the hash chain; exit 1 if broken
upbox checkpoint -o head.txt       # seal the current head so it can leave the machine
upbox doctor                       # at-rest protection, file modes, chain health
upbox export --format audit        # upbox.audit.v1 (chain proof + disclosures)
upbox prune --dry-run              # what retention would remove
upbox hold --since 2026-07-01      # exempt a range from retention
```

### Deploying on machines you don't own

upbox intercepts TLS. On an employee device that is employee monitoring, and
GDPR Article 88 leaves the rules largely to national law. In Italy, software
enabling remote monitoring of employees needs a union agreement or Labour
Inspectorate authorisation under Article 4 of Law 300/1970, and the Garante has
acted on it. Inform workers and their representatives first, and read the
Article 88 section of [docs/ai-act-mapping.md](docs/ai-act-mapping.md).

Running upbox on your own machine raises none of this.

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
# Run the full test suite (~7s)
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
                │  mitmproxy +     │    │ FastAPI + Jinja2 │     127.0.0.1
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

The proxy and dashboard never talk to each other directly. They share state through SQLite running in WAL mode: the proxy writes audit rows; the dashboard reads them. SQLite WAL is the IPC. mitmproxy is the proxy core (MIT-licensed, battle-tested). FastAPI + Jinja2 for the dashboard: server-rendered partials refreshed by a few hundred lines of vanilla JS, no build step, no JS framework.

## Threat model

**What upbox protects against**
- Surprise data egress from AI tools you already trust.
- Accidentally pasting `.env` contents or API keys into a cloud LLM.
- Compliance gaps where you need to answer "what did our laptops send to AI providers last month?"

**What upbox does not protect against**
- Tools that pin certificates and reject the local CA (some won't work without bypasses).
- Malicious local processes that read files directly without going through your tools.
- Data already exfiltrated before installation.
- Anyone with write access to `~/.upbox/upbox.db`. The hash chain makes edits *detectable*, not impossible. See "Tamper evidence" below.

**What upbox itself does**
- Reads your AI traffic via a local CA you install (and can uninstall).
- Stores audit data in `~/.upbox/upbox.db` (SQLite, owner-only permissions, not encrypted by upbox; see "At rest").
- Stores each request body up to a **100 KB cap** (`BODY_EXCERPT_MAX`), after redaction strips secrets. Bodies are recorded with a SHA-256 hash and their true size, so a truncated body is still provable and clearly marked in the dashboard rather than silently cut. The dashboard pretty-prints JSON bodies.
- Serves the dashboard on `127.0.0.1` only.
- Never makes outbound network calls of its own.

## At rest

**upbox does not encrypt its own database, on purpose.** It sets `~/.upbox` to
`0700` and the database to `0600`, and leaves encryption to the volume.

The reasoning is the key, not the cipher. upbox runs as an unattended daemon
that survives reboots, so any in-app encryption needs a key it can reach with no
human present. In practice that means a key file next to the database, which
defeats `strings upbox.db` and nothing else while letting a README claim
"encrypted at rest". A passphrase at every start breaks unattended restart and
gets disabled within a week. An OS keychain is right in principle but only stops
an attacker who does not already have the unlocked user session, which is the
session the daemon runs in.

The threat that actually happens to a laptop is theft or loss, and FileVault,
BitLocker and LUKS solve exactly that, with keys in a TPM or Secure Enclave that
no Python process can match. So turn one of them on:

| Platform | Enable | Check |
|---|---|---|
| macOS | System Settings, Privacy and Security, FileVault | `fdesetup status` |
| Windows | Settings, Privacy and Security, Device encryption | `manage-bde -status C:` |
| Linux | LUKS at install time, or `cryptsetup` | `lsblk -o NAME,TYPE` |

`upbox doctor` reports whether it is on, the database file modes, and the chain
status. It reports `UNKNOWN` rather than guessing when it cannot tell.

The stronger control is not storing the data in the first place: redaction
strips secrets before they are written, and retention (`body_days`, default 7)
clears stored bodies on a schedule. A body you never kept needs no key.

## Tamper evidence

Every captured request is chained: each row carries a SHA-256 over its own
fields plus the previous row's hash. `upbox verify` recomputes the chain.

```console
$ upbox verify
Chain OK: 18422 entries, seq 1-18422.
Head: e31d4c9f...
```

**What this detects:** edited content, deleted rows, inserted or reordered rows,
silent corruption, and a botched restore.

**What it does not detect.** The algorithm is public and keyless, so anyone with
write access to the database and a copy of upbox can recompute a perfectly
consistent chain over whatever contents they like. Deleting the last N entries
and rewinding the head produces a valid shorter chain. In the intended
deployment the person with that access is the person being audited.

The chain is worth something only once a head hash has left the machine. That is
what `upbox checkpoint` is for: it seals the current head so you can mail it to
yourself, commit it, or have it timestamped. upbox will not do that for you,
because it makes no outbound network calls, and that rule is worth more than
automatic anchoring would be.

The chain proves order, not time. Timestamps are unattested host wall clock.

## EU AI Act and GDPR mapping

upbox is a deployer-side tool. It does not certify you compliant on its own, but it produces the *evidence and controls* compliance demands:

| Obligation | Applies from | What upbox provides |
|---|---|---|
| **AI Act Article 4**: AI literacy | 2 Feb 2025 (amended 2026) | A visible, inspectable record of what AI tools are doing on your endpoints. The Digital Omnibus softened this to "take measures to support the development of AI literacy" and states it does not require guaranteeing any specific level. |
| **AI Act Article 50**: transparency | **2 Aug 2026** | Records of AI system interactions sufficient to support transparency duties toward affected persons. This is the obligation that actually landed in August 2026. |
| **AI Act Article 26**: deployer obligations | **2 Dec 2027** (Annex III), 2 Aug 2028 (Annex I) | Per-request audit log supporting Art. 26(1) use-per-instructions and Art. 26(5) monitoring. Note: the Art. 26(6) log-retention duty covers logs *automatically generated by the high-risk AI system itself*. upbox observes the network from outside the system, so its records are corroborating evidence, not those logs. |
| **GDPR Article 5**: data minimisation | in force | Redaction engine strips PII before forwarding. |
| **GDPR Article 30**: records of processing | in force | Per-tool destination and data-class inventory, exportable. |
| **GDPR Article 32**: security of processing | in force | Technical measure providing visibility + control over data leaving the endpoint. |
| **GDPR Article 35**: DPIA | in force | Provides concrete data flows to populate impact assessments. |

Today upbox's live legal anchors are GDPR and Article 50, not Article 26. Anyone selling you an "Article 26 compliance tool" for your coding assistant in 2026 is selling you a 2027 problem: a developer running Cursor or Copilot is generally not deploying an Annex III high-risk system at all.

upbox itself is not an AI system within the meaning of the Act. It is regex and rules written by people, which Recital 12 and the Commission's guidelines on the definition of an AI system place outside scope.

**Primary sources** (canonical ELI URLs, stable):

- AI Act full text: <https://eur-lex.europa.eu/eli/reg/2024/1689/oj>
- Digital Omnibus on AI, Regulation (EU) 2026/1744 (moved the high-risk dates): <https://eur-lex.europa.eu/eli/reg/2026/1744/oj>
- AI Act implementation timeline: <https://ai-act-service-desk.ec.europa.eu/en/ai-act/timeline/timeline-implementation-eu-ai-act>
- GDPR full text: <https://eur-lex.europa.eu/eli/reg/2016/679/oj>

**Article-by-article references.** These pages render the AI Act as published in June 2024 and do not yet reflect the 2026 Digital Omnibus amendments, so check dates and Article 4 wording against EUR-Lex:

- AI Act Art. 4: <https://artificialintelligenceact.eu/article/4/>
- AI Act Art. 26: <https://artificialintelligenceact.eu/article/26/>
- AI Act Art. 50: <https://artificialintelligenceact.eu/article/50/>
- AI Act Art. 113 (application dates): <https://artificialintelligenceact.eu/article/113/>
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
- **[Jinja2](https://jinja.palletsprojects.com)** (BSD-3-Clause): the dashboard templates, rendered server-side with no build step.
- **[SQLite](https://sqlite.org)** (public domain): the audit log store.
- **[Geist](https://vercel.com/font)** and **[JetBrains Mono](https://www.jetbrains.com/lp/mono/)**: the dashboard's sans + mono typefaces.
- **[Typer](https://typer.tiangolo.com)** (MIT): the CLI.

Full third-party license texts are preserved in [`LICENSES/`](LICENSES/).

## License

upbox is licensed under the **[MIT License](LICENSE)**.

## Contributing

upbox is pre-1.0 and moving fast. Issues, ideas, and PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, PR conventions, and the release process.

The fastest way to help right now: install v0.1 when it ships, run it against your daily AI tools, and report what surprised you.
