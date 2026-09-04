# Alternative install methods

The [README](../README.md#install) covers the three main paths: `pipx`, `uv tool`, and from source. The methods below are for edge cases.

All of them give you the same `upbox` command on `PATH`. Python 3.12+ is required.

> The PyPI package is named **`upbox-sh`** (the bare `upbox` name was already taken by an unrelated project). The command it installs is still **`upbox`**.

## uvx (no install, run once)

Run upbox without installing anything globally. uv resolves and caches deps the first time, then it's instant.

```sh
uvx --from upbox-sh upbox --help
uvx --from upbox-sh upbox init
uvx --from upbox-sh upbox start
```

The `--from upbox-sh` is required because the package (`upbox-sh`) and the command (`upbox`) have different names. Without it, uvx would try to fetch a package called `upbox`.

Good for one-shot smoke tests; less good as a daily driver because each command re-resolves.

## pip + venv (no extra tools)

```sh
python3 -m venv ~/.venvs/upbox
~/.venvs/upbox/bin/pip install upbox-sh
~/.venvs/upbox/bin/upbox --help

# Optional: symlink to PATH
ln -s ~/.venvs/upbox/bin/upbox ~/.local/bin/upbox
```

On Ubuntu 24+, Debian 12+, and recent Fedora, system `pip install` is blocked by [PEP 668](https://peps.python.org/pep-0668/). Use the venv above instead.

## Native binaries

Each release ships one-file executables built by PyInstaller on GitHub's
runners: Windows x86_64 (`.exe`), macOS Apple Silicon (`.dmg` holding the
`upbox` binary and a README), and Linux x86_64 (`.tar.gz`). They bundle Python,
mitmproxy, and mitmproxy's local-mode redirector for that platform, so nothing
else needs to be installed. The CLI is identical to the PyPI package. Each
binary is smoke-tested on its own platform (every command, the dashboard, and
the proxy in explicit-proxy mode) before it is attached to the release.

### Verify the download

Every asset has a `.sha256` file beside it.

```sh
sha256sum -c upbox-<version>-linux-x86_64.tar.gz.sha256      # Linux
shasum -a 256 -c upbox-<version>-macos-arm64.dmg.sha256      # macOS
certutil -hashfile upbox-<version>-windows-x86_64.exe SHA256  # Windows: compare with the .sha256 file
```

### macOS

```sh
open upbox-<version>-macos-arm64.dmg
cp /Volumes/upbox/upbox /usr/local/bin/upbox
chmod +x /usr/local/bin/upbox
xattr -d com.apple.quarantine /usr/local/bin/upbox
```

The `xattr` line removes the quarantine flag Safari and curl set on downloads.
Without it Gatekeeper refuses to run a binary that is not signed with an Apple
Developer certificate. Intel Macs are not built; use pipx.

### Windows

Rename the download to `upbox.exe` and put it somewhere on `PATH`. SmartScreen
shows "Windows protected your PC" once: click "More info", then "Run anyway".
PyInstaller one-file binaries occasionally trip Defender's heuristics; if the
file is quarantined, install with pipx instead and tell us in an issue.

Double-click `upbox.exe` to start it. Windows asks for administrator permission,
because OS-level capture installs a network driver. A console opens and, the
first time, asks before installing the local CA into your own user's Trusted
Root store. upbox then starts and the dashboard opens in your browser. Close the
window to stop upbox. If you decline the permission prompt, the window explains
the PowerShell commands instead:

```powershell
.\upbox.exe init     # one-time CA install
.\upbox.exe start    # needs an administrator PowerShell; add --open to open the dashboard
```

Once `upbox.exe` is on `PATH`, drop the `.\` prefix.

### Linux

```sh
tar -xzf upbox-<version>-linux-x86_64.tar.gz
sudo install upbox /usr/local/bin/upbox
```

Built on Ubuntu 22.04, so it needs glibc 2.35 or newer: Ubuntu 22.04, Debian 12,
Fedora 36, and anything later. Older distributions: use pipx.

### Why unsigned

Code-signing certificates cost money every year and the warnings they remove
are one click each. The checksums above let you verify what you downloaded; the
build runs in public on GitHub Actions from the tagged commit, so the binary is
reproducible in the sense that matters: you can read exactly how it was made.
If download numbers justify it, signing comes later.

### What the first start does

A one-file binary unpacks itself into a temporary directory on each start,
which costs about a second. `upbox start` launches the proxy and the dashboard
as two more copies of the same binary; they reuse the unpacked directory. OS-level
capture still needs admin or root, exactly as with the PyPI install.

## Install from a tag or branch

```sh
# Latest tagged release
pipx install git+https://github.com/krishnamallam/upbox.git@v0.1.0

# Latest main
pipx install git+https://github.com/krishnamallam/upbox.git@main

# Or via pip/venv
pip install git+https://github.com/krishnamallam/upbox.git@v0.1.0
```
