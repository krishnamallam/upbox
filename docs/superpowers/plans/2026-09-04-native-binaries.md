# Native Binaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship one-file `upbox` executables for Windows, macOS (arm64), and Linux, built and smoke-tested in the release workflow and attached to the GitHub release.

**Architecture:** A checked-in PyInstaller spec and entry script build the binary from the same environment that installed mitmproxy (whose own hooks bundle the local-mode redirectors). A `binaries` job in `release.yml` runs after `publish`, builds on the three platform runners, runs `packaging/smoke.sh` against the result, packages (`.tar.gz`, `.dmg`, `.exe`), and uploads to the release. The supervisor learns to spawn children from a frozen executable.

**Tech Stack:** PyInstaller 6, uv dependency groups, GitHub Actions matrix, `hdiutil`, `gh release upload`.

**Spec:** `docs/superpowers/specs/2026-09-04-native-binaries-design.md`

## Global Constraints

- No em-dashes anywhere. Ruff line length 100. mypy strict on `upbox/`.
- Tests: one assertion, AAA, no `if`/loops, monkeypatch module state rather than the interpreter.
- PyInstaller must run via `uv run pyinstaller` inside the project environment after `uv sync --group build`; never via `uv run --with pyinstaller`.
- Nothing in this plan runs `upbox erase`, `report`, or `start` against the real `~/.upbox`; the smoke script always sets `HOME` to a fresh temporary directory.
- Branch `feat/native-binaries` off `main` after the v0.3.0 release commit. Target version `v0.4.0 (unreleased)`; no tag in this plan.

---

### Task 1: Frozen-aware child command in the supervisor

**Files:** Modify `upbox/supervisor.py:104-107`; test `tests/test_supervisor.py`.

- [ ] Tests (append):

```python
def test_child_command_uses_module_form_when_not_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert supervisor._child_command(["proxy", "--port", "1"]) == [
        sys.executable, "-m", "upbox", "proxy", "--port", "1",
    ]


def test_child_command_reuses_the_frozen_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert supervisor._child_command(["dashboard"]) == [sys.executable, "dashboard"]
```

- [ ] Implement:

```python
def _child_command(args: list[str]) -> list[str]:
    """Argv for a child process, whether we run from source or from a frozen binary.

    A PyInstaller one-file build has ``sys.executable`` pointing at the binary
    itself, which already runs the Typer app, so ``-m upbox`` would reach it as
    unknown options. From source, ``-m upbox`` (via ``upbox/__main__.py``) is
    what invokes the app; ``-m upbox.cli`` would import and exit.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", SPAWN_MODULE, *args]


def _spawn(args: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(_child_command(args))
```

- [ ] Run `uv run pytest tests/test_supervisor.py -q`; commit `feat(supervisor): spawn children correctly from a frozen binary`.

### Task 2: Packaging inputs and the build dependency group

**Files:** Create `packaging/entry.py`, `packaging/upbox.spec`, `packaging/smoke.sh`, `packaging/README.txt`; modify `pyproject.toml`, `uv.lock`.

- [ ] `pyproject.toml`: add `build = ["pyinstaller>=6.11"]` under `[dependency-groups]`; run `uv lock`.
- [ ] `packaging/entry.py`, `packaging/upbox.spec`, `packaging/smoke.sh`, `packaging/README.txt` as in the spec (section 2). `smoke.sh` must be executable in git (`git update-index --chmod=+x`).
- [ ] Local proof on Linux: `uv sync --group build && uv run pyinstaller packaging/upbox.spec && packaging/smoke.sh dist/upbox`; all checks print `ok`.
- [ ] Commit `build: PyInstaller spec, entry point, and binary smoke test`.

### Task 3: Release workflow `binaries` job

**Files:** Modify `.github/workflows/release.yml`.

- [ ] Add `workflow_dispatch` to `on:`; guard the `publish` job with `if: github.event_name == 'push'` so a manual run builds binaries only.
- [ ] Narrow the publish job's release `files:` to `dist/*.whl` and `dist/*.tar.gz`.
- [ ] Add the `binaries` job per spec section 3, with `needs: publish` made conditional through `if: always() && (needs.publish.result == 'success' || github.event_name == 'workflow_dispatch')`, the three-runner matrix, build, smoke, package, checksum, and upload steps (upload only on `push`).
- [ ] Trigger `gh workflow run release.yml --ref feat/native-binaries` and wait; all three runners must pass build and smoke. Fix and repeat until green.
- [ ] Commit `ci: build, smoke-test, and attach native binaries on release`.

### Task 4: Documentation and version

**Files:** `README.md`, `docs/installing.md`, `CHANGELOG.md`, `ROADMAP.md`, `CLAUDE.md`, `pyproject.toml`, `upbox/__init__.py`.

- [ ] Version `0.4.0` in both places; `## v0.4.0 (unreleased)` changelog entry.
- [ ] README "Native binaries" subsection; `docs/installing.md` full section; ROADMAP v0.4 entry; CLAUDE.md release-workflow line.
- [ ] Staged-diff em-dash check; commit `docs: native binaries install path, v0.4.0 changelog`.

### Task 5: Verify and open the PR

- [ ] `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy upbox`.
- [ ] Push, open PR against `main`, wait for CI, report: PR URL, dispatch run URL with per-platform results, binary sizes.
