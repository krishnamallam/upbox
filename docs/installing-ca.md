# Installing the upbox CA

The upbox proxy speaks HTTPS to your AI tools, so they need to trust the
local certificate authority that upbox signs leaf certs with.

`upbox init` writes the CA to `~/.upbox/ca/upbox-ca.pem`, installs it to
the platform trust store, and prints copy-pasteable hints for tools that
read from non-system cert lists (Electron apps).

`upbox status` reports the trust state across every layer so you can
diagnose silent CA misses immediately.

## macOS

```sh
upbox init
```

This installs the CA to the **System keychain** (`/Library/Keychains/System.keychain`)
via `security add-trusted-cert`. You will be prompted for sudo / admin
authentication.

Verify with:

```sh
upbox status
# CA trust status:
#   Cert generated:        YES (~/.upbox/ca/upbox-ca.pem)
#   macOS System keychain: YES
```

Most macOS AI clients (Cursor, Claude Desktop, VSCode + Copilot) use the
System keychain by default, so no extra steps.

## Linux

Linux has **three different cert stores**, and different AI tools read
different ones. `upbox init` installs to all three:

| Layer | What reads from it | Method |
|---|---|---|
| System trust | `curl`, `wget`, system Python's `requests` | `/usr/local/share/ca-certificates/` + `update-ca-certificates` |
| NSS db | Firefox, Chrome (sometimes), some Electron apps | `certutil -d sql:~/.pki/nssdb` |
| Node bundled | Cursor, Claude Desktop, VSCode (Node-based Electron) | `NODE_EXTRA_CA_CERTS` env var |

```sh
upbox init
```

Output ends with:

```
For Electron apps (Cursor, Claude desktop, VSCode), launch with:
  NODE_EXTRA_CA_CERTS=$HOME/.upbox/ca/upbox-ca.pem <app>
Example:
  NODE_EXTRA_CA_CERTS=$HOME/.upbox/ca/upbox-ca.pem cursor
```

### `certutil` not found?

NSS install needs `certutil` (from `libnss3-tools` on Debian / Ubuntu, or
`nss-tools` on Fedora). `upbox init` prints a clear install command if it
is missing and skips the NSS step.

```sh
# Debian / Ubuntu
sudo apt install libnss3-tools

# Fedora
sudo dnf install nss-tools

# After installing, re-run:
upbox init
```

### Persistent `NODE_EXTRA_CA_CERTS`

To avoid re-typing the env var every time, add to `~/.bashrc` or `~/.zshrc`:

```sh
export NODE_EXTRA_CA_CERTS="$HOME/.upbox/ca/upbox-ca.pem"
```

Most Electron apps respect this on launch.

## Windows

```powershell
upbox init
```

This installs the CA to the Windows **per-user** Trusted Root
Certification Authorities store via `certutil -user -addstore`. No
admin rights needed — the install affects the current user only,
which is what Electron apps and most user-mode HTTPS clients read
from.

Verify with:

```powershell
upbox status
# CA trust status:
#   Cert generated:        YES
#   Windows Root store:    YES
```

For machine-wide install (every user on the box), run an elevated
shell and use the LocalMachine store directly:

```powershell
certutil -addstore -f "Root" "$env:USERPROFILE\.upbox\ca\upbox-ca.pem"
```

(The upbox CLI doesn't elevate itself; this is intentional — no
silent admin prompts.)

### Firefox on Windows

Firefox uses its own NSS database independent of the Windows store.
`upbox` doesn't write to it yet on Windows; trust the CA in Firefox
manually via Settings → Privacy & Security → Certificates → View
Certificates → Authorities → Import.

## Uninstalling

```sh
upbox init --uninstall
```

Removes the CA from every layer it was installed into. The files in
`~/.upbox/ca/` stay so a future `upbox init` doesn't have to generate a
new key. Delete the directory manually to fully wipe.
