# Development and release validation

End users install the thin skill with:

```text
npx skills add EnosElinsa/acquire-research-papers --skill acquire-research-papers -a codex -g
```

The canonical skill lives at `skills/acquire-research-papers/`; there is no root `SKILL.md`. The skill contains instructions, references, public schema snapshots, a standard-library launcher, and a fixed-wheel SHA-256 manifest. Python source, tests, development tools, runtime PowerShell/browser helpers, and the Git checkout are not installed as skill content.

## Developer setup and checks

```text
git clone https://github.com/EnosElinsa/acquire-research-papers.git
cd acquire-research-papers
uv sync --locked --all-groups
uv run ruff check src tests scripts skills/acquire-research-papers/scripts
uv run pytest -q
uv run python scripts/validate_skill.py .
node --test tests/node/test-ieee-playwright.mjs tests/node/test-ieee-profiles.mjs
```

On Windows, also run the credential-store, profile, and Playwright-installer suites under `tests/powershell/`. Tests use isolated temporary roots and public fixtures; never use real credentials or a real publication library for regression tests. `ARP_DATA_ROOT` and `ARP_RUNTIME_ROOT` permit isolated smoke runs. Review the exact-host boundaries and [source policies](skills/acquire-research-papers/references/source-policies.md) before changing an adapter. ScienceDirect remains manual only.

## Build wheel, thin skill, and ZIP

```text
uv run python scripts/build_distribution.py --update-source-manifest
uv run python scripts/validate_skill.py .
uv run python scripts/validate_skill.py dist/skills/acquire-research-papers
```

The builder pins `SOURCE_DATE_EPOCH`, builds the actual release wheel, computes its SHA-256, refreshes the canonical `runtime.json` and public schema snapshots, and exports an explicit allowlist to `dist/skills/acquire-research-papers/` and a versioned ZIP. Runtime scripts are explicitly included in the wheel alongside public JSON schemas; developer scripts are excluded. The builder rejects `.git` destinations, repository/source replacement, links, and unexpected files in an existing exported skill. It never publishes a release or overwrites an installed skill.

After any runtime source or packaged README/schema/helper change, rebuild and refresh the manifest. The manifest is an integrity pin for that exact wheel, not a proof that a release was uploaded. Validate the artifact digest before publishing. Do not claim remote install success until both the tagged source and fixed wheel URL are actually available.

## Isolated installed-skill smoke

Use a temporary copy of the exported skill and the actual locally built wheel. Set `ARP_LOCAL_WHEEL` to its absolute path; the launcher still requires the manifest SHA-256 to match. Set `ARP_RUNTIME_ROOT` and `ARP_DATA_ROOT` to separate temporary directories, then run:

```text
python <temporary-skill>/scripts/arp.py --help
python <temporary-skill>/scripts/arp.py config status
python <temporary-skill>/scripts/arp.py library audit <temporary-library> --metadata <empty-object.json> --output <temporary-audit>
```

Exercise an offline author fixture and a reviewed temporary import/organize/apply/rollback plan. Inspect the installed wheel ZIP to confirm `_scripts/` and `_schemas/` are present and `tests/`, `build_distribution.py`, and `validate_skill.py` are absent. Confirm imports resolve inside the isolated runtime, with no checkout on `PYTHONPATH`.

To test Skills discovery itself, run the standard installer against a temporary local source copy containing only the canonical skill subtree, under a temporary HOME/USERPROFILE, with `--skill acquire-research-papers -a codex -g -y`. Keep all installer outputs inside that temporary home; inspect the resulting skill files and run its launcher using the local-wheel override. This validates installation layout without publishing or touching the user's real installed skills.

Release publishing is a separate explicitly authorized operation. Build and test first; do not create a GitHub release, push a tag, or upload artifacts as part of ordinary validation.

## Publishing a release

Update both READMEs, CHANGELOG.md, the Python version, and the runtime manifest together. Run the full supported test matrix, build the final wheel/ZIP, then verify their hashes and a separate installed runtime. Build after any change to packaged source, helpers, schemas, or README metadata. The manifest itself is outside the CLI wheel, so updating its digest does not change that wheel.

Publish only after the source commit is on `main` and CI is green. Tag that exact commit as `v<version>`. Upload the matching wheel, versioned thin-skill ZIP, and a `SHA256SUMS` file listing their hashes.

`scripts/release.py` performs the mechanical steps; each prints one JSON object and stops at the first failed check:

```text
uv run python scripts/release.py bump <new-version> [--date YYYY-MM-DD]
uv run python scripts/release.py build [--output <fresh-directory>]
uv run python scripts/release.py smoke
uv run python scripts/release.py publish --title "v<version> — <summary>" --notes-file <notes.md>
uv run python scripts/release.py smoke --public
uv run python scripts/release.py remote --host <user@host> [--target kiro|codex]
```

`smoke` extracts the built skill ZIP into a temporary directory, bootstraps it from the built wheel (or, with `--public`, from the published release URL) in isolated roots without API keys, and runs live checks: version and runtime pin, `--open-all` in `manual-fetch --help`, the venue preset list and two preset routes, fetches from ACL, AAAI, NeurIPS, PMLR, CVF, IJCAI, Springer, and Elsevier (Springer delivers only on an entitled network and otherwise must be `access_required`; Elsevier must be `access_required`), ICML 2023 discovery through the PMLR index (1,828 papers with abstracts and official URLs) and an unchanged rerun, and a background fetch. A fetch that ends `network_transient` or `rate_limited` is retried once after 30 seconds into a fresh folder, and its report line says "(after a retry)". Each check records what it expected and observed; any failure exits 1.

`remote` installs the built skill ZIP on a Linux or macOS host over key-based SSH (`BatchMode`, so it never prompts). The host is an argument and is never written anywhere. It copies the ZIP and `SHA256SUMS` into a fresh staging folder in the remote home, checks the ZIP hash there, moves each installed skill to `~/.arp-skill-backups/<.kiro|.codex>-acquire-research-papers-<UTC stamp>`, installs into `~/.kiro/skills` and `~/.codex/skills` (or the `--target` given), and then requires each skill's `--version` and `doctor` to report the new version with a matching runtime pin. The first `--version` downloads the pinned wheel from the public release URL, so run `remote` after `publish`. To roll back, move the backup folder back into place.

`scripts/check_sources.py` is the live upstream check that the `weekly source check` workflow runs every Monday (and on demand): every preset ISSN must still name its journal in Crossref and have records in the last full year, every proceedings DOI must have records, every OpenAlex source must resolve to itself with works two years back, and each official index (ACL, IJCAI, NeurIPS, PMLR, CVF) must list close to its known paper count with a few sample paper pages that still parse with an abstract. The smoke's open-access fetches (ACL, AAAI, NeurIPS, PMLR, CVF, IJCAI) run through `arp fetch` in throwaway roots without keys and must deliver; `--only presets|indexes|fetches` runs one group. A check that fails with a connection error, HTTP 5xx, or HTTP 429 runs once more after 30 seconds and is marked `retried`; if it fails that way again, its status is `upstream_error`, which is listed in the report and shown as a workflow warning but does not fail the run, since nothing in this repository can fix a remote server fault. Error text keeps only the host of each URL. OpenAlex checks need the `OPENALEX_API_KEY` repository secret (`gh secret set OPENALEX_API_KEY`) and are skipped without it; locally, `--use-configured-keys` reads the key `arp config` stores.

`bump` rewrites the version in `pyproject.toml`, `__init__.py`, the project entry of `uv.lock`, the release-pinned test fixtures, the release sections of both READMEs, and the `## Unreleased` CHANGELOG heading (to `## <version> — <date>`), and writes nothing if any file is not as expected. `build` builds into `dist/release-<version>` (which must not exist yet), refreshes `runtime.json`, rebuilds in a temporary directory to prove the wheel and ZIP byte-reproducible, checks that both READMEs link the new release tag, that `CHANGELOG.md` has the new section, and that the wheel's embedded README links the tag (bump's README and CHANGELOG edits once went missing before a build), and writes `SHA256SUMS` with LF lines. Then smoke-test the assets, commit and tag the release, and push `main` and the tag yourself. `publish` checks that the working tree is clean, that `origin` has `main` and the tag at `HEAD`, and that every `test` workflow run for that commit passed (`--skip-ci-check` overrides only this check); it then creates a draft release, uploads each asset with retries, checks the uploaded sizes, publishes the draft as latest, and downloads the assets again to compare hashes. A draft left by an interrupted `publish` is reused; an already published release is refused. Prepare release notes from the changelog with installation, migration, platform limits, and validation evidence. Never replace assets under an already published version; a correction to published runtime bytes needs a new version and digest.

The `verify public release` workflow runs after publication on Linux, Windows, and macOS. It installs the tagged skill with the real Skills installer and bootstraps its public wheel URL with no local-wheel override. The workflow can also be dispatched against a named tag or branch. Verify the default-branch installation command as well, since that is the documented user path. GitHub source archives are developer downloads; the skill ZIP is the manual-install artifact.

## Safe copy and checkout migration

Preserve any existing Git checkout, including one previously used directly as an installed skill. Never ask the external Skills installer to overwrite that checkout. Build the export, select a separate directory outside every checkout, and use:

```text
python scripts/install_skill.py --source dist/skills/acquire-research-papers --target <new-skill-directory>
python scripts/install_skill.py --source dist/skills/acquire-research-papers --host claude-code
python scripts/install_skill.py --source dist/skills/acquire-research-papers --host kiro-cli
```

The installer accepts only the explicit thin-skill allowlist. It refuses target `.git` files/directories, nested Git metadata, Git-checkout ancestors, source/target overlap, and symbolic links. Existing targets require `--replace` and must already be clean thin skills. Replacement preserves a sibling `.previous-...` backup and restores it if the final rename fails. Runtime state and credentials remain outside the installed skill and are not copied. The installer is developer tooling and is excluded from the CLI wheel and distributed skill.

`--host` chooses the documented user skill directory for Codex, Claude Code, Kiro IDE or Kiro CLI; `--project-root` can select a project path but does not bypass the Git-checkout refusal. See [host setup and resources](skills/acquire-research-papers/references/hosts.md). Validate host discovery/invocation separately from CLI installation, and record version, OS, date and scope. Do not treat synthetic CI or a present `SKILL.md` as real-host certification.
