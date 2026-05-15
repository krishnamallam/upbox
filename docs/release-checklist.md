# v0.1.0 release checklist (Day 14)

This is the runbook for actually shipping. Days 1–13 build the product;
this is the publish.

## Pre-flight

- [ ] All open PRs (Day 4 through Day 13 stack) merged into `main`.
- [ ] CI green on `main`.
- [ ] `uv run upbox --help` works on a clean checkout.
- [ ] You ran upbox for a full work day (Day 13). Top 3 annoyances fixed.
- [ ] Launch screenshot captured. Save under `launch/screenshot.png`
      (~1600×900 ideal, dashboard with real traffic + tiles + one
      striking request).
- [ ] `docs/configuring-tools.md` has up-to-date URLs and screenshots
      for each AI tool covered.
- [ ] CHANGELOG.md v0.1.0 entry accurate.

## Version bump

```sh
# In pyproject.toml, change:
#   version = "0.0.1"
# to:
#   version = "0.1.0"

git checkout -b release/v0.1.0
git commit -am "release: v0.1.0"
git tag v0.1.0
```

## PyPI publish

A GitHub Action publishes on tag push. To do it manually:

```sh
uv build           # produces dist/*.whl and dist/*.tar.gz
uv publish         # needs PYPI_TOKEN env var
```

Verify with `pipx install upbox==0.1.0` in a clean shell.

## Push the tag

```sh
git push origin main
git push origin v0.1.0
```

## Launch posts

In this order, spaced 5–10 minutes apart so the first one isn't
buried by your other posts:

1. **HN Show.** Title and body from `launch/hn.md`. Replace
   `<repo URL>` and `<docs URL>`. Post around 09:00 ET on a weekday
   for best chance of front page.
2. **X / Twitter.** Thread from `launch/x-thread.md`. Replace
   numbers in tweet 1 with the real numbers from your screenshot.
   Add `<screenshot URL>` (or upload directly to X). Add `<repo URL>`.
3. **Reddit.** `launch/reddit.md` has separate copy for r/selfhosted
   and r/privacy. Don't post both in the same hour — spread by
   2–3 hours.

## Post-launch

- [ ] Monitor for 6 hours minimum. Reply to every comment in the
      first 90 minutes — that's the algorithm window.
- [ ] Watch for issues / questions in GitHub Issues. First-day bugs
      are usually setup/CA-trust related; the FAQ should cover most.
- [ ] If HN climbs front page, expect 3–10× traffic. The dashboard
      handles it (it's local). The repo and docs are what get hit.
- [ ] Capture any "I tried it and saw X" replies for v0.2 testimonial
      content.

## v0.2 cadence

Right after launch ship the compliance lens (~16 days to 1 August):

1. Article 26 export format
2. Tamper-evident hash chain
3. Encrypted-at-rest SQLite
4. Team mode (basic)
5. Windows CA auto-install
6. Live-reload of rule files

Same launch arc on the eve of EU AI Act enforcement.
