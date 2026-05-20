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

When you Ctrl+C, the proxy and dashboard shut down and the OS network
redirector unwinds cleanly — no leftover state, no risk of stranding
the machine with a dead proxy.

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
