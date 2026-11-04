# Changelog

## Unreleased

- Corpus and research acquisition checkpoint the ledger after every paper. An interrupted run resumes with the same command: verified pairs are adopted, the interrupted paper's leftovers move to `.arp-interrupted/`, any other blocking file is named, and `run status` reports `interrupted`.
- One failure classification serves every acquisition path. Publishers without an adapter enter the manual queue as `unsupported_adapter`; publisher 5xx, DOI resolver network failures, and IEEE navigation failures are retryable; unexpected browser failures are `automation_error` and report only the exception class. `fetch` reports publisher HTTP errors without a traceback.
- DOI resolution retries with backoff, follows DOI alias hops, and maps Elsevier link-resolver targets to the manual ScienceDirect route. `--defer-host` matches DOI-only records of supported publishers. Publisher HTTP clients back off 1, 2, then 4 seconds.
- IEEE papers of one run share one dedicated browser (`ARP_IEEE_REUSE_BROWSER=0` opts out); page steps are bounded at 120 s separately from the user's login wait; a transient citation export is retried before the downloaded PDF is discarded. The pinned Playwright installer now accepts the runtime data root.
- Batches space requests per publisher host and pause a host for the rest of the run after HTTP 429, three consecutive transient failures (`host_paused`), or an institution login failure. `doctor` reports IEEE browser prerequisites.
- Tests are isolated from real configuration: `AppPaths.for_root()` no longer lets `ARP_CONFIG_ROOT` override its explicit root.
- `SKILL.md` routes every mode, adds one result-to-next-action table, and is the single copy of the access boundaries; examples use the portable `arp` shorthand.

## 0.6.0 — 2026-10-21

- New research runs write only discovery state until evidence review, then one `reports/report.md` with located evidence, claim coverage, pending work, scope and an applicable bounded gap conclusion. `evidence research --export-csv` adds merged `papers.csv` and `claim-coverage.csv`; runs without `output_version` keep their legacy layout on resume.
- Author discovery and library audit default to JSON plus a brief report; `--export-csv` enables spreadsheet views. Resolved metadata/research/download queues disappear and absent paths return JSON null. Hash-bound corpus review queues and acquisition `paper-manifest.csv` remain for compatibility.
- Added offline `arp sources` and `arp sources --spec <corpus.yaml>` inventory/venue-year diagnostics. Official ACL/IJCAI indexes, metadata enumeration, artifact acquisition and observed coverage are distinguished. Priority venues remain unselected; no claim of complete conference/journal coverage or new live certification is made.
- Reduced the main skill to three common routes with advanced references; combined Related Work and gap analysis into a shared recipe and reorganized bilingual output guidance by workflow and phase. Official raw BibTeX, identity checks, frozen hashes, recovery, backup/rollback and access boundaries are preserved.

## 0.5.0 — 2026-10-20

- Added independent capability commands for identity, discovery, enrichment, collections, reviews, immutable selection, acquisition, local verification, PDF parsing, evidence validation and export, with lightweight hash-checked run status and recovery. Existing corpus/research/author entrypoints and frozen identities remain compatible.
- New installations use editable local dotenv credentials, explicit file selection, no interpolation, private permissions, isolated institution files, and non-secret status. Existing DPAPI stores remain selected until explicit conflict-safe migration on the original Windows account.
- Shared v2 review provenance records the actual host and available model metadata while preserving legacy Codex review bytes/hashes. Added host-aware safe copy targets, read-only local `doctor --host`, Codex/Claude Code/Kiro installation guidance and a Kiro `skill://` resource template. Documentation compatibility is separate from live host validation.
- Added seven composition recipes with input templates, expected outputs, recovery and limits. Official PDF/raw BibTeX pairing, exact credential hosts, institution/browser isolation, manual ScienceDirect interaction and library backups/rollback remain in force.

## 0.4.0 — 2026-10-20

This is the first packaged GitHub release. It includes the previously developed acquisition, corpus, and research commands alongside the following additions.

### Institution access

- Named IEEE institution profiles isolate configuration, DPAPI credentials, and browser sessions. `direct`, `assisted`, and explicit-contract `carsi` access are separate choices; first setup defaults to assisted manual login.
- Added `config setup`, IEEE `list/use/login/doctor`, non-secret form inspection, typed locators, and legacy single-institution migration. Existing PowerShell entrypoints remain available.
- Manual login retains its visible browser until completion, cancellation, or timeout. MFA and unfamiliar pages require user action; transport retries do not resubmit credentials.
- Diagnostics distinguish configuration, authentication, IEEE return, verified artifacts, and institutional entitlement. Historical timestamps are explicit; failed live checks replace older success records. Open-access downloads do not prove subscription access.

### Local libraries and authors

- Added `library audit/update/import/organize/apply`, staged hash-bound changes, backup/journal recovery, idempotent apply, rollback, and concurrent-apply protection.
- PDF version evidence, citation placement, first-online dates, and formal issue dates are recorded separately. Unverified identities and multi-DOI ambiguities require review.
- Original BibTeX bytes, BOM, encoding, line endings, and hash-bound publisher provenance are preserved. IEEE export strings remain verbatim.
- Added title-based paired filenames, explicit chapter identity/page maps with retained source books, and a bounded manual ScienceDirect queue/watch/import workflow.
- Added public author discovery across ORCID, DBLP, supplied homepages, and Crossref. Formal publications, Early Access, and preprints remain separate; issue dates are primary, identities may be ambiguous, and source coverage is never claimed complete.

### Installation

- The sole source skill is `skills/acquire-research-papers/`. Standard `npx skills add` installs this small subtree.
- The portable launcher verifies a fixed release wheel and installs it with uv outside the skill. The wheel carries runtime browser/PowerShell helpers and schemas; user skill packages exclude source checkouts and development dependencies.
- Added exported skill folders, a downloadable ZIP, runtime schema output, and a safe copy installer that refuses Git checkouts.
- Added bilingual installation/migration guidance, troubleshooting, structured issue templates, release checksums, and public-install verification.

### Validation and limits

Python, Node, and PowerShell regressions use synthetic/redacted fixtures and temporary stores. Public-install smoke tests exercise the real release download without a local-wheel override. Windows remains required for IEEE browser/DPAPI workflows; public metadata and local-library operations remain portable. This release does not establish live validation for every institution, universal author completeness, or measured cross-domain search precision/recall. ScienceDirect page/login automation remains outside the supported workflow.

Earlier development history is available in the [commit log](https://github.com/EnosElinsa/acquire-research-papers/commits/main/); no earlier packaged GitHub releases were published.
