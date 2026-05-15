# Configuring AI tools to use the upbox proxy

After `upbox init` (CA trusted) and `upbox start` (proxy listening on
`127.0.0.1:8888`, dashboard on `http://127.0.0.1:8800`), point each AI
tool at the proxy.

## Cursor

**Launch with the upbox CA env var (Linux/macOS):**

```sh
NODE_EXTRA_CA_CERTS=$HOME/.upbox/ca/upbox-ca.pem HTTPS_PROXY=http://127.0.0.1:8888 cursor
```

Cursor doesn't expose proxy config in its settings UI yet, so we rely on
the `HTTPS_PROXY` env var (respected by Node's `undici`/`https` clients).

## Claude Desktop / Claude Code

**Linux / macOS:**

```sh
NODE_EXTRA_CA_CERTS=$HOME/.upbox/ca/upbox-ca.pem HTTPS_PROXY=http://127.0.0.1:8888 claude
```

For the Anthropic Python SDK:

```sh
HTTPS_PROXY=http://127.0.0.1:8888 REQUESTS_CA_BUNDLE=$HOME/.upbox/ca/upbox-ca.pem python your_script.py
```

## GitHub Copilot (VSCode)

VSCode has built-in proxy settings:

1. Settings → search `http.proxy`
2. Set to `http://127.0.0.1:8888`
3. Set `http.proxyStrictSSL` to `true` (the upbox CA is trusted, so strict SSL is fine)

If using VSCode on Linux, also launch with `NODE_EXTRA_CA_CERTS` so
Copilot's Node runtime trusts the CA:

```sh
NODE_EXTRA_CA_CERTS=$HOME/.upbox/ca/upbox-ca.pem code
```

## ChatGPT (web)

In Firefox/Chrome:

1. Settings → Network → Manual proxy → `127.0.0.1:8888`
2. Visit `https://chat.openai.com` — traffic appears in the upbox feed.

Some browsers cache trust decisions per-origin. If the page errors,
clear the browser's HSTS for `chat.openai.com` (Chrome:
`chrome://net-internals/#hsts`).

## OpenAI / Anthropic API directly

For `curl`:

```sh
curl --proxy http://127.0.0.1:8888 \
     --cacert $HOME/.upbox/ca/upbox-ca.pem \
     https://api.openai.com/v1/chat/completions \
     -H "Authorization: Bearer $OPENAI_API_KEY" \
     -d '{ "model": "gpt-4o-mini", "messages": [...] }'
```

For Python SDKs (set `HTTPS_PROXY` and `REQUESTS_CA_BUNDLE` env vars
before importing the client).

## What doesn't work (yet)

- **Certificate-pinned apps.** A handful of mobile and some specialised
  desktop clients ship with hard-coded CA fingerprints and refuse any
  CA they don't know. There's no workaround for those without
  modifying the app binary.
- **Windows auto-install** is manual in v0.1 (see `installing-ca.md`).
