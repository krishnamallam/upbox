# Configuring AI tools to use the upbox proxy

After `upbox init` (CA trusted) and `upbox start` (proxy on
`127.0.0.1:8888`, dashboard on `http://127.0.0.1:8800`), route each tool
through upbox. The fastest path is `upbox run <tool>`.

## `upbox run <tool>` (recommended)

`upbox run` finds the tool's installed executable, then spawns it as a
child process with `HTTPS_PROXY` + `NODE_EXTRA_CA_CERTS` set (or, for
browsers, `--proxy-server` and an isolated user-data directory). Only
that one process is proxied — the rest of the system isn't touched, so
you can't accidentally cut your machine's internet if upbox crashes.

```sh
upbox run claude         # Claude Desktop (Electron)
upbox run claude-code    # Claude Code CLI (npm)
upbox run cursor         # Cursor
upbox run code           # VS Code (covers Copilot + Codeium extensions)
upbox run chrome         # Chrome with --proxy-server (ChatGPT-web, Gemini-web)
upbox run --list         # show all supported tools
```

Works the same on Linux, macOS, and Windows. On Windows, `upbox run`
expands `%LOCALAPPDATA%` / `%PROGRAMFILES%` and locates the tool
without any PowerShell or env-var setup.

## Browser-based tools (ChatGPT, Gemini, Claude.ai)

Browsers ignore `HTTPS_PROXY` env vars, so `upbox run chrome` passes
`--proxy-server=http://127.0.0.1:8888` and uses an isolated profile
under `~/.upbox/profiles/chrome/`. Existing Chrome logins and cookies
stay untouched.

```sh
upbox run chrome
# inside the launched window, navigate to chatgpt.com / gemini.google.com / claude.ai
```

To route Firefox the same way, set its proxy in Settings → Network
Settings → Manual proxy → `127.0.0.1:8888`. Firefox uses its own NSS
database; import the upbox CA via Settings → Privacy → Certificates →
View Certificates → Authorities → Import (`~/.upbox/ca/upbox-ca.pem`).

## Without `upbox run` (manual env vars)

If your tool isn't in `upbox run --list`, set the env vars yourself.

### Linux / macOS

```sh
NODE_EXTRA_CA_CERTS=$HOME/.upbox/ca/upbox-ca.pem HTTPS_PROXY=http://127.0.0.1:8888 your-tool
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

- **Certificate-pinned apps.** A few desktop AI clients ship hard-coded
  CA fingerprints and refuse any CA they don't know. No workaround
  without modifying the app binary.
- **Tools launched by an updater.** Some apps (Squirrel-based
  installers) re-exec themselves on first run and lose the env vars
  set on the initial `upbox run` invocation. If you see the tool
  bypassing the proxy after an auto-update, restart it via
  `upbox run <tool>` again.
