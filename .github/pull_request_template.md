## Problem and change

<!-- What problem does this solve, and how does the behavior change? Link the issue, e.g. "Fixes #123". -->

## Validation

<!-- The checks you ran (pytest, ruff, validate_skill.py, Node or PowerShell suites, live fetches) and any material limits. -->

## Checklist

- [ ] Tests cover the changed contract; a bug fix includes a test that fails without it.
- [ ] `CHANGELOG.md` has a line under `## Unreleased`.
- [ ] The English and Chinese documentation pages under `docs-site/` (and the README summaries or skill references where they apply) describe user-visible changes.
- [ ] No credentials, browser or session data, signed URLs, downloaded papers, or runtime stores are included.
- [ ] Publisher and institution changes keep exact-host boundaries and use redacted fixtures.
- [ ] Library writes handle source changes, collisions, and recovery; raw citation bytes and frozen corpus/research contracts are preserved.

<!-- Releases follow the steps in CONTRIBUTING.md ("Publishing a release") with scripts/release.py. -->
