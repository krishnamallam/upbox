# X / Twitter launch thread

> Template. Replace `<screenshot URL>` and the numbers in tweet 1 with
> real values captured from a Day-10 dogfooding session.

---

**Tweet 1 — hook**

I installed upbox and watched Cursor send <N> KB of my private repo to
<M> domains in <T> seconds.

It's a local proxy + dashboard that audits what your AI tools actually
send to the cloud. MIT licensed. Runs entirely on your machine.

<screenshot URL>

🧵

**Tweet 2 — what**

upbox sits between your AI tools and the cloud and logs every request:

- Per-tool tiles (Cursor, Claude, Copilot, ChatGPT, …)
- Full headers + 4 KB body excerpt per request
- Regex redaction strips API keys, .env vars, GitHub tokens before forwarding
- Per-tool destination allowlist; warn or block unknown hosts

**Tweet 3 — install**

One-time setup on Linux / macOS:

```
pipx install upbox
upbox init        # generates + installs local CA
upbox start       # spins up proxy + dashboard
```

Then point your AI tools at `127.0.0.1:8888` and open
`http://127.0.0.1:8800`.

**Tweet 4 — why now**

EU AI Act full enforcement begins 2 August 2026. Most orgs have AI
policies, almost none have endpoint-level evidence of what their tools
are doing.

upbox produces the audit log Article 26 wants, locally, with zero
cloud telemetry.

**Tweet 5 — local-only**

The auditor itself has to be inspectable, so:

- No outbound calls from upbox beyond proxying the requests your tools
  were going to make anyway
- Dashboard refuses to bind to anything but 127.0.0.1
- Open source — the only way to trust a tool that watches your AI

<repo URL>

**Tweet 6 — what's next**

v0.1 ships today. v0.2 (the compliance lens — Article 26 export
format, tamper-evident hash chain, team mode) lands 1 August.

If you build with AI tools, install once and run it for a week. The
first screenshot is usually a surprise.

<repo URL>
