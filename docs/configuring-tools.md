# Capturing AI tool traffic with upbox

After `upbox init` (trusts the local CA) and `upbox start`, upbox runs
mitmproxy in **LocalMode** — an OS-level traffic redirector that
intercepts HTTPS at the network layer for every process on the machine.
Same model as Wireshark/Charles Proxy. No per-tool configuration, no
system-proxy registry edits, no `HTTPS_PROXY` env vars.

## `upbox start` — one command

```sh
upbox start
```

Boots:
- mitmproxy on `127.0.0.1:8888` with LocalMode capture
- dashboard on `127.0.0.1:8800`

By default, only HTTPS traffic to known AI hosts gets MITM'd (the
allowlist; see below). Everything else — your browser, Outlook,
Teams, banking, OS telemetry — passes through untouched.

When you Ctrl+C, the proxy and dashboard shut down and the OS network
redirector unwinds cleanly — no leftover state, no risk of stranding
the machine with a dead proxy.

## TLS allowlist (default ON)

upbox derives a TLS allowlist from the `hosts` field of every rule in
`upbox/rules/tools.yaml` (or `~/.upbox/rules/tools.yaml` if you have
your own copy). The current shipped list includes:

- `api.anthropic.com`, `chat.openai.com`, `chatgpt.com`,
  `api.openai.com`, `api.cursor.sh`, `api2.cursor.sh`,
  `api.githubcopilot.com`, `copilot-proxy.githubusercontent.com`,
  `server.codeium.com`, `generativelanguage.googleapis.com`

Subdomains of each entry match too — `api.anthropic.com` covers
`europe.api.anthropic.com` as well.

Adding new AI hosts is a one-line edit to `tools.yaml` (also editable
via the dashboard's Settings page).

For ad-hoc additions without editing the file:

```sh
upbox start --allow other-ai-tool.example.com
upbox start --allow foo.example.com --allow bar.example.com
```

To disable the allowlist (capture every host, knowing it'll break
pinned-cert apps):

```sh
upbox start --no-allowlist
```

This makes upbox behave like a full transparent proxy. Useful for
debugging or compliance-scenarios where you need everything captured,
not just AI traffic. Expect Outlook, Teams, OneDrive, many mobile
apps, and some banks to stop working until you stop upbox.

### Admin / root requirement

LocalMode hooks the OS network layer. First run requires elevation:

| Platform | What it uses | First-run prompt |
|----------|-------------|------------------|
| Windows  | WinDivert kernel driver | UAC prompt to install the driver |
| Linux    | iptables / nftables     | `sudo upbox start`, or run as root |
| macOS    | Network Extension       | "Allow extension" in System Settings |

After the driver/extension is approved once, subsequent runs may not need
admin (Windows). Linux always needs root for raw iptables.

If LocalMode isn't available, upbox prints the reason from
`mitmproxy_rs.local.LocalRedirector.unavailable_reason()` (e.g.,
"mitmproxy is not running as root") and exits. Fall back to regular
mode:

```sh
upbox start --capture-spec ""
```

…which boots mitmproxy in standard explicit-proxy mode. You'd then route
tools manually with `HTTPS_PROXY=http://127.0.0.1:8888` (recipes below).

## Filtering what gets captured

`--capture-spec` accepts mitmproxy's LocalMode intercept syntax. Default
is `!__upbox_disabled__` (sentinel exclude → captures everything).

```sh
upbox start --capture-spec "claude.exe,cursor.exe,code.exe"   # AI tools only
upbox start --capture-spec "!firefox,!chrome"                  # exclude browsers
upbox start --capture-spec ""                                  # disable LocalMode
```

Process matching is by executable name. The mitmproxy docs have the full
grammar.

## Fallback: manual env vars (when LocalMode isn't an option)

If you can't get admin/root, run upbox in regular mode and route tools
yourself:

### Linux / macOS

```sh
NODE_EXTRA_CA_CERTS=$HOME/.upbox/ca/upbox-ca.pem HTTPS_PROXY=http://127.0.0.1:8888 your-app
```

### Windows PowerShell

```powershell
$env:HTTPS_PROXY = "http://127.0.0.1:8888"
$env:NODE_EXTRA_CA_CERTS = "$env:USERPROFILE\.upbox\ca\upbox-ca.pem"
& "C:\path\to\your-tool.exe"
```

### Anthropic / OpenAI Python SDKs

```sh
HTTPS_PROXY=http://127.0.0.1:8888 REQUESTS_CA_BUNDLE=$HOME/.upbox/ca/upbox-ca.pem python your_script.py
```

### `curl`

```sh
curl --proxy http://127.0.0.1:8888 \
     --cacert $HOME/.upbox/ca/upbox-ca.pem \
     https://api.openai.com/v1/chat/completions \
     -H "Authorization: Bearer $OPENAI_API_KEY" \
     -d '{ "model": "gpt-4o-mini", "messages": [...] }'
```

## What doesn't work (yet)

- **Certificate-pinned apps.** A few desktop and mobile clients ship
  hard-coded CA fingerprints and refuse any CA they don't know. No
  workaround without modifying the app binary.
- **Apps that bypass the OS network stack entirely.** Rare, but
  some VPN clients and kernel-mode networking apps may evade even
  LocalMode.
