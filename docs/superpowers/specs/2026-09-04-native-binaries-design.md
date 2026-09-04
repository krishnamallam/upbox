# Native binaries: one-file upbox for Windows, macOS, and Linux

Design spec, 2026-09-04. Implements the "Native binaries" item from
`ROADMAP.md`: a single-file executable per platform so non-Python users can
install upbox in one download. Targets v0.4.0.

## Goals

- `upbox.exe` for Windows x86_64, a `.dmg` for macOS (Apple Silicon), and a
  `.tar.gz` for Linux x86_64, each containing one self-contained `upbox`
  executable with the same CLI as the PyPI package.
- Built and smoke-tested on the real platform runners in CI, attached to the
  GitHub release by the existing release workflow, so a tag produces PyPI
  wheels and binaries in one go.
- No behaviour change for pipx or uv users. The frozen build and the package
  share every line of application code; only process spawning learns that it
  may be frozen.

## Non-goals

- Code signing and notarisation. Unsigned binaries trigger Gatekeeper and
  SmartScreen warnings; the docs explain the two clicks that get past them.
  A signing certificate is a later, separate decision once download numbers
  justify the cost.
- Intel macOS. The `macos-latest` runner is Apple Silicon; Intel users keep
  pipx. Adding an Intel job is a one-line matrix change when a runner with a
  long support window is available.
- An AppImage, Homebrew formula, winget or Chocolatey manifest, or installers
  with wizards. The tarball, the dmg, and the exe are the deliverables.
- Auto-update. Binaries are pinned to their release; users download the next
  one.

## Feasibility, established by a spike on 2026-09-04

A one-file PyInstaller build of the current tree on Linux produces a 52 MB
`upbox` executable. Inside it, `upbox --help`, `verify`, `report`, and
`doctor` run correctly against a scratch `HOME`. Two facts from the spike
shape the design:

- `mitmproxy_rs` ships its own PyInstaller hooks (registered through the
  `pyinstaller40` entry point). They bundle the platform redirector for local
  mode: the `mitmproxy-linux-redirector` script on Linux, the
  `mitmproxy_macos` app bundle on macOS, WinDivert and the Windows redirector
  on Windows. mitmproxy itself ships hooks for its `script` module and web
  assets. Nothing needs to be hand-listed for mitmproxy.
- The Linux hook resolves the redirector through `sysconfig.get_path("scripts")`,
  so PyInstaller must run inside the same environment that installed
  mitmproxy. `uv run --with pyinstaller` layers an ephemeral environment whose
  scripts directory is empty and the build fails. PyInstaller therefore lives
  in a `build` dependency group and runs via `uv run pyinstaller` after
  `uv sync --group build`.

## Design

### 1. Frozen-aware supervisor

`upbox start` spawns its two children with `[sys.executable, "-m", "upbox", ...]`.
In a frozen binary `sys.executable` is the binary itself and `-m upbox` would
reach Typer as unknown options. `supervisor._child_command(args) -> list[str]`
returns `[sys.executable, *args]` when `getattr(sys, "frozen", False)` is
true and the current form otherwise; `_spawn` uses it. PyInstaller's
bootloader reuses the parent's extraction directory for a child that runs the
same one-file binary, so the children start without a second unpack.

### 2. Packaging inputs, checked in

- `packaging/entry.py`: the PyInstaller entry script. Imports `upbox.cli.app`
  and calls it. Exists because PyInstaller wants a script path, not a module.
- `packaging/upbox.spec`: one spec for all three platforms. `Analysis` over
  `packaging/entry.py` with `datas = collect_data_files("upbox") +
  collect_data_files("publicsuffix2") + collect_data_files("certifi")`,
  `hiddenimports = collect_submodules("uvicorn")` (uvicorn imports its loop
  and protocol implementations by string), `excludes = ["tkinter", "tcl", "tk"]`.
  One-file `EXE` named `upbox`, console, no UPX. `collect_data_files("upbox")`
  picks up the rule YAML, `schema.sql`, and the dashboard templates and
  static files, all of which the code reads through `importlib.resources`.
- `packaging/smoke.sh`: the acceptance test for a built binary, POSIX shell so
  it runs on Git Bash on the Windows runner too. Given the binary path, it
  sets `HOME` (and `USERPROFILE` on Windows) to a fresh temporary directory
  and asserts: `--help` lists `erase` and `report`; `verify` reports an empty
  chain; `report` starts with the report title; `doctor` prints the database
  path; `dashboard --port 18800` answers `/` and `/transparency` with 200
  within ten seconds; `proxy --port 18888` in explicit-proxy mode prints its
  starting line within ten seconds. Local mode is not exercised: it needs
  root and, on macOS, a system-extension approval no runner can grant.
- `pyproject.toml`: `[dependency-groups] build = ["pyinstaller>=6.11"]`, and
  `uv.lock` updated.

### 3. Release workflow

`.github/workflows/release.yml` gains a `binaries` job after `publish`:

- `needs: publish`, so the GitHub release already exists when assets upload.
- Matrix: `ubuntu-latest` (linux, x86_64, `.tar.gz`), `macos-latest` (macos,
  arm64, `.dmg`), `windows-latest` (windows, x86_64, `.exe`).
- Steps: checkout, `astral-sh/setup-uv` with Python 3.12, `uv sync --group
  build --frozen`, `uv run pyinstaller packaging/upbox.spec`, run
  `packaging/smoke.sh dist/upbox` (or `dist/upbox.exe`), package, then
  `gh release upload "$GITHUB_REF_NAME" <asset> --clobber`.
- Packaging per platform: Linux `tar -czf upbox-<version>-linux-x86_64.tar.gz
  -C dist upbox`; macOS `hdiutil create -volname upbox -srcfolder <folder
  containing upbox and a README.txt> -format UDZO
  upbox-<version>-macos-arm64.dmg`; Windows copies `dist/upbox.exe` to
  `upbox-<version>-windows-x86_64.exe`. `<version>` comes from the tag.
- `SHA256SUMS.txt`: each job writes its own `sha256` line and uploads it as
  `upbox-<version>-<platform>.sha256`, so the release page carries checksums
  without a cross-job merge step.
- The existing publish job's `files: dist/*` becomes `dist/*.whl` and
  `dist/*.tar.gz`, which stops the stray `default.gitignore` asset that
  `uv build` leaves behind.
- The whole job also runs on `workflow_dispatch` (build and smoke only, no
  upload) so the pipeline can be exercised on a branch before a tag exists.

### 4. Documentation

- README "Install" gains a "Native binaries" subsection above pipx: download
  the file for your platform from the releases page, make it executable,
  the two Gatekeeper and SmartScreen clicks, and that `upbox start` still
  needs admin or root for OS-level capture. Points to `docs/installing.md`
  for details.
- `docs/installing.md` gains the full section: per-platform steps, the
  quarantine attribute command on macOS, SmartScreen "More info, Run anyway",
  the checksum file, that binaries are unsigned and why, and that Intel Mac
  and other architectures use pipx.
- `CHANGELOG.md`: `## v0.4.0 (unreleased)` with the binaries under Added,
  the frozen-aware supervisor under Changed, and the release-asset glob fix
  under Internal.
- `ROADMAP.md`: native binaries move from Later to a v0.4 entry.
- `CLAUDE.md`: a line under Git and release workflow describing the binaries
  job, the `build` group, and the spike's environment pitfall.

### 5. Testing

- Unit: `tests/test_supervisor.py` gains two tests for `_child_command`:
  frozen returns `[sys.executable, *args]`; not frozen returns the `-m upbox`
  form. Both monkeypatch `sys.frozen` rather than rely on the real
  interpreter state.
- Smoke: `packaging/smoke.sh` runs in CI on every platform for every tag, and
  locally against the spike build on Linux before this ships.
- Pipeline: one `workflow_dispatch` run on the feature branch, all three
  runners green, before the PR is opened.

## Error handling

- A smoke failure fails the job before any upload, so a broken binary never
  reaches the release page while the PyPI publish stands.
- `gh release upload --clobber` makes re-runs idempotent.
- The frozen check is a pure function; if a future runtime hides `sys.frozen`,
  the fallback is the current behaviour, which fails loudly with Typer's
  unknown-option error rather than silently doing the wrong thing.

## Decisions taken

- PyInstaller over Nuitka or a Rust rewrite: mitmproxy publishes its own
  PyInstaller hooks and ships its own PyInstaller builds, so it is the path
  with the least unknowns.
- One-file over one-directory: a single download is the point. Start-up pays
  a one-time unpack of about a second.
- Binaries built in the release workflow after publish, not in a separate
  workflow, to avoid two workflows racing to create the same release.
- Unsigned for now, documented honestly, revisited on demand.
