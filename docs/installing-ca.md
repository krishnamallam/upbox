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

Auto-install is **not yet supported** in v0.1 (planned for v0.2). For
now, double-click `~/.upbox/ca/upbox-ca.pem` (or use `certutil -addstore`)
to import the CA into **Trusted Root Certification Authorities**.

```powershell
certutil -addstore -f "Root" "$env:USERPROFILE\.upbox\ca\upbox-ca.pem"
```

## Uninstalling

```sh
upbox init --uninstall
```

Removes the CA from every layer it was installed into. The files in
`~/.upbox/ca/` stay so a future `upbox init` doesn't have to generate a
new key. Delete the directory manually to fully wipe.
