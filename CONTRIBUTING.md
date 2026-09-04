# Contributing to upbox

upbox is pre-1.0 and moving fast. Issues, ideas, and PRs welcome.

## Filing issues

- **Bugs:** include your OS, Python version, the output of `upbox status`, and steps to reproduce.
- **Feature requests:** describe the use case, not just the feature. The "why" matters more than the "what".
- **Security:** if you find a vulnerability, please email instead of opening a public issue. See [README — Threat model](README.md#threat-model) for what's in scope.

## Dev setup

```sh
git clone https://github.com/krishnamallam/upbox.git
cd upbox
uv sync --dev
```

Common commands:

```sh
uv run pytest -v                        # full suite (~4s)
uv run pytest tests/test_capture.py -v  # single file
uv run ruff check . && uv run ruff format .
uv run mypy upbox
uv run upbox --help                     # run the CLI from your checkout
```

See [README — Development](README.md#development) for the full list.

## Pull requests

1. Fork, branch off `main`, commit, push, open a PR against `main`.
2. Run `pytest`, `ruff check`, `ruff format --check`, and `mypy upbox` before pushing. CI runs the same on Ubuntu, macOS, and Windows — it will catch you otherwise.
3. Keep PRs focused: one logical change per PR. Easier to review, easier to revert.
4. Use conventional-commit prefixes in the PR title: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`.
5. Update [`CHANGELOG.md`](CHANGELOG.md) under the `## vX.Y.Z (unreleased)` heading when your change is user-visible (create the heading for the next version if it does not exist yet).

## Project conventions

The project's load-bearing decisions live in [`CLAUDE.md`](CLAUDE.md) at the repo root:

- mitmproxy is the proxy core. We use its addon API; we never fork it.
- Two long-running processes (`upbox proxy`, `upbox dashboard`) spawned by `upbox start` (supervisor). IPC is **only** via SQLite WAL. Never embed mitmproxy inside FastAPI.
- SQLite via stdlib `sqlite3` in WAL mode. No ORM.
- FastAPI + Jinja2 server-rendered partials with vanilla JS and CSS for the dashboard. No build step, no frontend framework.
- The dashboard binds to `127.0.0.1` only.
- upbox itself makes no outbound calls beyond the proxied requests it forwards.

Code-quality and testing rules live under [`.claude/rules/`](.claude/rules/):

- [`testing.md`](.claude/rules/testing.md) — verify behavior not implementation, one assertion per test, real implementations over mocks.
- [`code-quality.md`](.claude/rules/code-quality.md) — naming, file organization, anti-defaults.
- [`security.md`](.claude/rules/security.md) — parameterized queries, no secrets in logs, constant-time comparisons.
- [`error-handling.md`](.claude/rules/error-handling.md) — typed exceptions, addon failures must not crash the proxy.

## Release process (maintainers)

Releases are automated by [`.github/workflows/release.yml`](.github/workflows/release.yml), triggered when you push a `v*` tag.

### One-time GitHub setup

The release workflow depends on two non-default settings that must be in place for the workflow to succeed:

1. **`contents: write` permission** in the workflow's `permissions:` block — required for [`softprops/action-gh-release`](https://github.com/softprops/action-gh-release) to create the GitHub Release and generate its notes. Without this, the release step fails with `Resource not accessible by integration`. This is already set in `release.yml`; if you fork, double-check it's still there.
2. **PyPI trusted publishing** configured at <https://pypi.org/manage/account/publishing/> for the `upbox-sh` project, pointing at this repo, the `release.yml` workflow file, and the `pypi` environment. This avoids storing a long-lived PyPI token in repo secrets and is the path the workflow takes by default. If trusted publishing isn't configured, fall back to `UV_PUBLISH_TOKEN` via `secrets.PYPI_TOKEN`.

The PyPI publish step uses `skip-existing: true` so a re-run after a partial failure won't choke on PyPI's "file already exists" error.

### Cutting a release

1. Bump `version` in [`pyproject.toml`](pyproject.toml) and `__version__` in `upbox/__init__.py`; they must match.
2. Date the `## vX.Y.Z (unreleased)` heading in [`CHANGELOG.md`](CHANGELOG.md) as `## vX.Y.Z (YYYY-MM-DD)` and mark the milestone shipped in [`ROADMAP.md`](ROADMAP.md).
3. Commit the bump, open a PR, get it merged into `main`.
4. Tag the merge commit and push the tag:
   ```sh
   git checkout main && git pull
   git tag v0.1.0
   git push origin v0.1.0
   ```
5. The release workflow fires, verifies the tag matches `pyproject.toml`, builds the sdist + wheel, publishes to PyPI, and creates the GitHub Release with auto-generated notes.

The "Verify tag matches pyproject version" step fails if the tag (e.g. `v0.1.0`) doesn't match the version in `pyproject.toml` (e.g. `0.1.0`). This is intentional — it prevents publishing a wheel whose version disagrees with its tag.
