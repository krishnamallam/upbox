# upbox

> Wireshark for your AI tools. See, audit, and control what they send.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Status: pre-release](https://img.shields.io/badge/status-pre--release-orange.svg)](#roadmap)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](#)

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
- **Audit log.** JSON Lines + CSV export. Tamper-evident hash chain.
- **Local-only.** SQLite on disk. The dashboard binds to `127.0.0.1` only. No outbound calls from upbox itself.

## Vision: one capture engine, many lenses

Every request your AI tools make gets captured locally. *Lenses* render that captured data for different needs:

| Lens | Question it answers | Target |
|---|---|---|
| **Live feed** | What are my AI tools doing right now? | v0.1 |
| **Compliance** | Can I prove what left the endpoint? (EU AI Act, GDPR, SOC 2, ISO 27001) | v0.2 |
| **Cost** | How much am I spending, per tool, per model, per project? | v0.3 |
| **Prompt history** | What did I ask Cursor about Postgres last Tuesday? | v0.4 |
| **Security** | Did anyone leak a secret or source-code? Is a tool calling a host it shouldn't? | v0.5 |
| **Tool inventory** | Which AI tools is the team actually using, how often? | v0.6 |
| **Quality / fine-tuning** | Which interactions are good enough to curate as training data? | v0.7 |
| **Debug replay** | This AI tool used to work, what changed? Replay the exact request. | v0.8 |

Compliance is one of eight uses, not the whole product. The EU AI Act window triggers the first compliance launch — but upbox is built for the next decade of AI in development, not one enforcement deadline.

One capture engine. Many lenses. Each lens is small (~1 week of work) once the foundation exists. A plugin SDK in v1.0 lets the community ship lenses we haven't thought of.

## Quick start

```bash
# Install
pipx install upbox

# Generate and install the local CA (one time)
upbox init

# Boot the proxy + dashboard
upbox start
#  Proxy:     http://127.0.0.1:8888
#  Dashboard: http://127.0.0.1:8800

# Configure your AI tool to use the proxy, then open the dashboard
```

Per-tool setup recipes: [docs/configuring-tools.md](docs/configuring-tools.md).

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

The EU AI Act window (full enforcement begins 2 August 2026) is what triggers the first compliance launch in v0.2 — but the compliance lens will cover multiple frameworks, not just one. Articles below are the *first* mapping; SOC 2, ISO 27001, and NIS 2 follow in the same lens.

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

**Foundation: v0.1 — capture engine + live feed lens** (target: 15 July 2026)

- Local CA setup, mitmproxy bootstrap
- Tool fingerprinting (Cursor, Claude desktop, Copilot, ChatGPT, Codeium)
- SQLite audit log
- Regex redaction engine
- Lens-aware dashboard (`/lens/{name}/...`) — ships with the **live feed lens**
- JSONL + CSV export

The foundation is built so every later lens is a 1-week sprint. No dashboard rewrite, no capture engine changes — just a new route, a template, and a few queries.

**Lens sprints (each ≈ 1 week after v0.1):**

| Version | Lens | Target | Why now |
|---|---|---|---|
| v0.2 | Compliance | 1 Aug 2026 | EU AI Act full enforcement begins next day |
| v0.3 | Cost | Aug 2026 | Spend on cloud LLMs is the biggest unmeasured line item in most companies' AI budgets |
| v0.4 | Prompt history | Sept 2026 | Everyone has lost an answer they got two weeks ago |
| v0.5 | Security | Sept–Oct 2026 | Source-code egress incidents will keep happening |
| v0.6 | Tool inventory | Oct 2026 | Enterprise AI governance push — "which tools are even running on our laptops?" |
| v0.7 | Quality / fine-tuning | Nov 2026 | Open-source fine-tuning workflows need curated data |
| v0.8 | Debug replay | Dec 2026 | When an AI tool breaks and you have no idea why |

Each version is a launch moment. The targets after v0.2 are intentions, not commitments — early-adopter signal decides the order.

**v1.0 — platform graduation** (target: early 2027)

- Plugin SDK: third parties ship lenses as installable packages
- macOS menu-bar app, Windows tray app
- Enterprise team mode (LAN-local central dashboard, still no cloud)
- Browser extension companion for web-only AI tools

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
