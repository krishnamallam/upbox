# Writing redaction rules

upbox strips secrets from request bodies **before forwarding** to the
cloud LLM. Patterns are loaded from `~/.upbox/rules/redact.yaml`
(falling back to bundled defaults if absent).

You can edit the YAML in-place, or use the dashboard's `/settings` page.
After editing, restart `upbox start` for changes to apply (live reload
lands in v0.1.1).

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

## Bundled defaults (v0.1)

| Name | Pattern | Catches |
|---|---|---|
| `aws-access-key` | `AKIA[0-9A-Z]{16}` | AWS IAM access key IDs |
| `openai-key` | `sk-[A-Za-z0-9]{32,}` | OpenAI API keys |
| `anthropic-key` | `sk-ant-[A-Za-z0-9-]{32,}` | Anthropic API keys |
| `github-token` | `ghp_[A-Za-z0-9]{36}` | GitHub personal access tokens |
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
2. Restart `upbox start`.
3. Make an AI request containing the secret you want to test.
4. Open the request detail in the dashboard — the `Redactions` field
   shows `applied: [<rule-name>]` if the rule fired.

If you don't see the rule firing:

- Check `Content-Type` — binary bodies are skipped.
- Check the request actually hit the proxy (`upbox status`).
- Check the regex against `regex101.com` in Python mode.
