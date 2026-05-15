# EU AI Act and GDPR mapping

upbox is a **deployer-side** technical measure. It does not certify
you compliant — but it produces the evidence and controls that
compliance assessments demand.

EU AI Act full obligations for high-risk systems take effect
**2 August 2026**.

## AI Act articles

### Article 4 — AI literacy (in force since Feb 2025)

upbox provides a visible, inspectable record of what AI tools are
doing on your endpoints. Real artefacts beat policy slides:

- Dashboard shows live traffic by tool, host, request size.
- Audit log is queryable and exportable.
- Per-tool allowlist enforces destination policy.

### Article 26 — Deployer obligations (logging, monitoring, human oversight)

The audit log table (`requests` in `~/.upbox/upbox.db`) records:

| Field | Article 26 relevance |
|---|---|
| `ts` | Timestamp of every interaction |
| `tool` | Which AI system was used |
| `method`, `scheme`, `host`, `path` | Destination of the call |
| `req_bytes`, `resp_bytes`, `status` | Size and outcome |
| `headers_json` | Full request headers |
| `body_excerpt` | First 4 KB of the request body |
| `body_hash` | SHA-256 of the full body for integrity |
| `redactions_applied_json` | What redaction rules fired |
| `blocked` | Whether enforcement intervened |

Export with `upbox export --format jsonl|csv [--since TS --until TS --tool NAME]`.

### Article 50 — Transparency (applies 2 Aug 2026)

upbox records every AI-system interaction so deployers can support
transparency duties toward affected persons. The record covers what
was sent, when, where, by which tool, in what size and with what
status.

### Article 99 — Penalties

upbox helps demonstrate good-faith effort: concrete technical
measures (audit log, redaction, enforcement), retention, and
exportable evidence.

## GDPR articles

### Article 5 — Principles (data minimisation)

The redaction engine strips PII (AWS keys, OpenAI keys, Anthropic
keys, GitHub tokens, dotenv variables — extendable) **before**
the request reaches the cloud LLM. The body the provider sees is
already minimised.

### Article 32 — Security of processing

upbox is a technical measure providing visibility + control over
data leaving the endpoint. Trust store: local-only CA the user
installs and can uninstall. Dashboard: `127.0.0.1` only, never a
public interface.

### Article 35 — DPIA

Concrete per-tool data flows feed DPIA templates:

| Tool | Destinations | Data classes seen | Volume |
|---|---|---|---|
| Cursor | api.cursor.sh, api2.cursor.sh | prompt text, file content | from audit log |
| Claude Code | api.anthropic.com | prompt text | from audit log |
| (etc.) | | | |

`upbox export --format csv` produces a spreadsheet feedable to a DPIA
process.

## Primary sources

- AI Act full text: <https://eur-lex.europa.eu/eli/reg/2024/1689/oj>
- AI Act implementation timeline: <https://ai-act-service-desk.ec.europa.eu/en/ai-act/timeline/timeline-implementation-eu-ai-act>
- GDPR full text: <https://eur-lex.europa.eu/eli/reg/2016/679/oj>
- AI Act Art. 4: <https://artificialintelligenceact.eu/article/4/>
- AI Act Art. 26: <https://artificialintelligenceact.eu/article/26/>
- AI Act Art. 50: <https://artificialintelligenceact.eu/article/50/>
- AI Act Art. 99: <https://artificialintelligenceact.eu/article/99/>
- GDPR Art. 5: <https://gdpr-info.eu/art-5-gdpr/>
- GDPR Art. 32: <https://gdpr-info.eu/art-32-gdpr/>
- GDPR Art. 35: <https://gdpr-info.eu/art-35-gdpr/>

upbox is not legal advice. Consult counsel for compliance certification.
