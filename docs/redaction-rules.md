# Writing redaction rules

upbox strips secrets from request bodies **before forwarding** to the
cloud LLM. Patterns are loaded from `~/.upbox/rules/redact.yaml`
(falling back to bundled defaults if absent).

You can edit the YAML in-place, or use the dashboard's `/settings` page.
As of v0.1.2, edits apply automatically: the running proxy reloads `tools.yaml`,
`redact.yaml`, and `allowlist.yaml` within ~2 seconds, no restart needed. (Adding
a brand-new host to intercept still requires an `upbox start` restart.)

## Schema

```yaml
- name: <human-readable rule name>
  pattern: <Python regex>
  replace: <literal string>
  multiline: <bool, optional, default false>
```

- `pattern` is a Python regular expression. Test patterns at
  <https://regex101.com> with the Python flavour.
- `replace` is the literal substitution string. It is treated as
  bytes, not a template — `\1`, `\g<name>` etc. are not expanded.
- `multiline: true` enables `re.MULTILINE` so `^` and `$` match at
  each line, not just the start/end of the body.

## Bundled defaults (v0.1.2)

| Name | Pattern | Catches |
|---|---|---|
| `aws-access-key` | `AKIA[0-9A-Z]{16}` | AWS IAM access key IDs |
| `anthropic-key` | `sk-ant-[A-Za-z0-9_-]{20,}` | Anthropic API keys (incl. `sk-ant-api03-…`) |
| `openai-key` | `sk-(?:proj-\|svcacct-\|admin-)?[A-Za-z0-9_-]{32,}` | OpenAI keys (legacy + `sk-proj-…`) |
| `google-api-key` | `AIza[0-9A-Za-z_-]{35}` | Google API keys |
| `slack-token` | `xox[baprs]-[0-9A-Za-z-]{10,}` | Slack tokens |
| `github-fine-grained` | `github_pat_[0-9A-Za-z_]{22,}` | GitHub fine-grained PATs |
| `github-server-token` | `ghs_[A-Za-z0-9]{36}` | GitHub server tokens |
| `github-token` | `ghp_[A-Za-z0-9]{36}` | GitHub classic PATs |
| `bearer-token` | `Bearer\s+[A-Za-z0-9._~+/=-]{8,}` | `Authorization: Bearer` values |
| `dotenv-block` | `^[A-Z_][A-Z0-9_]*=.+$` (multiline) | One `.env` line at a time |

## How redaction is applied

The redact addon dispatches by `Content-Type`:

- `application/json` (and `*+json`): the body is parsed, every string
  value is regex-substituted, and the result is re-serialised. JSON
  structure is preserved.
- `text/*`: byte-level regex on UTF-8-decoded body.
- Anything else (binary, octet-stream, multipart): **skipped**. The
  dashboard surfaces this via the `Redactions` field on the request
  detail view (`skipped: binary or unsupported content-type: ...`).

The body the cloud LLM sees is the redacted version. The dashboard
shows what was redacted (rule name + count) so you can verify the
rule actually fired.

## Writing your own rule

Add an entry to your YAML:

```yaml
- name: stripe-secret
  pattern: "sk_live_[A-Za-z0-9]{24,}"
  replace: "[REDACTED:stripe-secret]"
```

Or your own internal token:

```yaml
- name: acme-corp-token
  pattern: "ACME-[A-Z0-9]{16}"
  replace: "[REDACTED:acme-token]"
```

## Verifying a rule

1. Edit `~/.upbox/rules/redact.yaml` (or use the `/settings` page).
2. Wait ~2 seconds — the running proxy applies rule-file changes automatically,
   no restart needed (a restart is only needed when adding a brand-new
   intercepted host).
3. Make an AI request containing the secret you want to test.
4. Open the request detail in the dashboard — the `Redactions` field
   shows `applied: [<rule-name>]` if the rule fired.

If you don't see the rule firing:

- Check `Content-Type` — binary bodies are skipped.
- Check the request actually hit the proxy (`upbox status`).
- Check the regex against `regex101.com` in Python mode.
