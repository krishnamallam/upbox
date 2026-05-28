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

## Install from a tag or branch

```sh
# Latest tagged release
pipx install git+https://github.com/krishnamallam/upbox.git@v0.1.0

# Latest main
pipx install git+https://github.com/krishnamallam/upbox.git@main

# Or via pip/venv
pip install git+https://github.com/krishnamallam/upbox.git@v0.1.0
```
