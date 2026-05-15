# FAQ

## Does upbox phone home?

**No.** upbox makes zero outbound network calls of its own. The proxy
forwards the requests your AI tools were going to make anyway — that's
the entire network footprint. The dashboard binds to `127.0.0.1`
only and refuses to start on any other host.

## What happens to my request bodies?

They are stored locally in `~/.upbox/upbox.db` (SQLite, WAL mode). The
`body_excerpt` column holds the first 4 KB; full bodies are not
persisted. `body_hash` (SHA-256 of the full body) is recorded for
integrity.

The 4 KB cap is intentional — it keeps the database small while
preserving enough context for the dashboard. Adjust the
`BODY_EXCERPT_MAX` constant in `upbox/db/store.py` if you need more.

## How big does the database get?

Per request: ~5 KB on average (headers + 4 KB body excerpt + metadata).
Heavy use (~500 requests/day from Cursor, Claude, ChatGPT combined) is
roughly 2.5 MB/day or ~900 MB/year. Configurable retention lands in
v0.2; for now, manual:

```sh
sqlite3 ~/.upbox/upbox.db \
  "DELETE FROM requests WHERE ts < datetime('now', '-30 days');"
```

## Performance impact on the AI tools?

Negligible for typical AI usage. The mitmproxy core handles tens of
thousands of requests per second; AI tools peak in the low hundreds per
hour. Latency added per request: ~1–5 ms.

If you see noticeable slowdown, profile with mitmproxy's
`--set stream_large_bodies=10m` to stream rather than buffer.

## Why is my dashboard empty?

Run `upbox status` first. The doctor command checks every layer:

```
CA trust status:
  Cert generated:        YES (~/.upbox/ca/upbox-ca.pem)
  Linux system trust:    YES
  Linux NSS:             YES
```

If any layer says `NO`, the corresponding tool category won't
intercept. See [`installing-ca.md`](installing-ca.md) for fixes.

If trust is good but no traffic shows up, the AI tool isn't using the
proxy. Check `HTTPS_PROXY` env var, VSCode settings, or browser proxy
config.

## Some apps pin certificates and reject the local CA

A handful of mobile and certain desktop clients ship with hard-coded
CA fingerprints. Without modifying the app binary, you can't MITM
them. We list known-working tools in
[`configuring-tools.md`](configuring-tools.md) and known-broken ones
in the README.

## Can I run upbox in a team / multi-endpoint setup?

Not in v0.1. Team mode (LAN-local central dashboard) is planned for
v0.2. v0.1 is single-machine.

## Is upbox open source?

Yes. MIT licensed. <https://github.com/krishnamallam/upbox>

## Does upbox replace mitmproxy?

No — upbox **uses** mitmproxy as its proxy core. upbox is the
addons (capture, fingerprint, redact, enforce), the schema, the
dashboard, the CA management, and the supervisor. mitmproxy
handles the TLS interception and HTTP semantics.

## Is the audit log tamper-evident?

Not in v0.1. The `body_hash` column proves each captured body is
intact, but the row sequence itself isn't chained. Tamper-evident
hash chain (each row's hash includes the previous row's hash)
lands in v0.2 as part of the compliance lens.

## Can I extend upbox with a new tool fingerprint or redaction rule?

Yes. Edit `~/.upbox/rules/tools.yaml` (or `redact.yaml`, or
`allowlist.yaml`), or use the dashboard's `/settings` page. Restart
`upbox start` to apply.

## How do I uninstall completely?

```sh
upbox init --uninstall   # remove CA from trust stores
rm -rf ~/.upbox/         # remove cert, db, rules, supervisor PID
pipx uninstall upbox
```
