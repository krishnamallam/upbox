# Reddit launch posts

## r/selfhosted

**Title:**

upbox — local proxy that audits everything your AI tools send to the cloud (MIT)

**Body:**

Hey r/selfhosted,

I shipped a small tool that fills a gap I kept hitting: when I press
Tab in Cursor or paste into Claude, I have no good way to verify
what's actually leaving my machine.

upbox is a local proxy + dashboard that records every AI request,
strips secrets before forwarding, and runs entirely on 127.0.0.1.
Single Python process (mitmproxy + FastAPI + SQLite), MIT licensed,
no telemetry, no cloud anything.

Features:

- Per-tool fingerprinting (Cursor, Claude desktop + Code, Copilot,
  ChatGPT, Codeium, …)
- Content-aware redaction — parses JSON properly, handles gzip
- Per-tool destination allowlist
- Live dashboard with per-tool tiles + request feed + click-through detail
- JSONL / CSV export

Install:

```
pipx install upbox
upbox init
upbox start
```

Repo: https://upbox.sh

Looking for testers, especially Linux folks on Ubuntu with Cursor or
Claude desktop. The Day-2 setup hits all three Linux cert stores
(system trust + NSS + NODE_EXTRA_CA_CERTS) so it should Just Work.

---

## r/privacy

**Title:**

I built upbox so I could see what my AI tools were actually sending. Local-only, MIT.

**Body:**

Every AI tool I use says "we don't send more than we have to" and the
docs are vague enough that I never trust it. So I built a thing that
shows me.

upbox is a local proxy that intercepts your AI tools' traffic, shows
you every request in a dashboard, and lets you strip secrets (API
keys, .env contents, etc.) before forwarding.

- 127.0.0.1 only — refuses to bind to a public interface.
- No outbound calls from upbox itself; it just forwards what your
  tools were going to send anyway.
- Open source, MIT. Because a closed-source privacy tool is itself a
  privacy problem.

Repo: https://upbox.sh

Curious what surprises people on first run. The screenshot is usually
the marketing campaign — open it for 30 seconds with Cursor active and
you'll see things you didn't expect.
