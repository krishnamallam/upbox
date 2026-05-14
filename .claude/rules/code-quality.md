---
alwaysApply: true
---

# Code Quality

## Anti-defaults (counter common Claude tendencies)

- No premature abstractions. Three similar lines beats a helper used once.
- Don't add features or improvements beyond what was asked.
- Don't refactor adjacent code while fixing a bug.
- No dead code or commented-out blocks. Git has history.
- WHY comments, never WHAT. If code needs a "what" comment, rename instead.
- API docs at module boundaries only, not every internal function.

## Naming

- Files and modules: `snake_case.py`. Test files: `test_<module>.py`.
- Classes: `PascalCase`. Functions and variables: `snake_case`. Module-level constants: `SCREAMING_SNAKE`.
- Booleans: `is_` / `has_` / `should_` / `can_` prefix. Predicates: `is_*` / `has_*`.
- Private members with `_leading_underscore`. Reserve dunder (`__name__`) for genuine magic methods.
- Abbreviations only when universally known (`id`, `url`, `api`, `db`, `auth`). Acronyms lowercase in identifiers: `user_id`, `http_status`.

## Code Markers

`TODO(author): desc (#issue)` for planned work. `FIXME(author): desc (#issue)` for known bugs. `HACK(author): desc (#issue)` for ugly workarounds (explain the proper fix). `NOTE: desc` for non-obvious context. Owner and issue link required. Never `XXX`, `TEMP`, `REMOVEME`.

## File Organization

- Imports: stdlib, third-party, first-party, local relative. Blank line between groups (ruff isort handles this).
- One public class per module when the class is the module's reason for existing. Helpers stay private (`_leading_underscore`).
- Function order: public API first, then helpers in call order.
- Type hints on every public function. `from __future__ import annotations` at the top of every module.
