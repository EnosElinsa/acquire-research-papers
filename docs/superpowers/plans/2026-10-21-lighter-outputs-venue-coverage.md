# Lighter outputs and explicit venue coverage implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for independent implementation and review tasks. User approved P0–P4 and commit, push and release on 2026-10-21.

**Goal:** Separate resumable evidence from optional exports, delay research reports until evidence review, and make venue coverage inspectable without claiming exhaustive literature coverage.

**Architecture:** Keep existing state and frozen-selection contracts. New research runs use output version 2; old runs resume with their original layout. Human reports are derived views. Venue diagnostics are offline capability descriptions, separate from observed per-run coverage.

**Tech stack:** Python 3.11+, existing HTTP/HTML/JSON Schema stack, pytest, portable thin skill and pinned wheel.

**Spec:** The approved P0–P4 plan in this chat; this document records its implementation decisions and file contract.

## Global constraints

- Preserve publisher PDF/raw BibTeX verification, immutable selection hashes, provenance, review evidence, manual handoff, backups and rollback.
- Keep legacy runs readable and resumable without migrating immutable artifacts.
- State remains at its current paths; no new service, orchestration engine or universal plugin system.
- ScienceDirect remains manual-only. No new credential handling or access-boundary changes.
- User has not selected priority venues. Ship a reviewed inventory for existing ACL/IJCAI/IEEE/ACM/ScienceDirect examples and a diagnostic for arbitrary requested venue/year slices. Do not invent coverage or add speculative adapters.
- Export absence is represented as null/omitted paths, never the string "None". Required state always remains on disk.

## P0: File contract and preflight

Baseline: 663 passed, 1 Windows symlink-permission skip. Starting commit 6c4589c. Original checkout contains pre-existing deleted scripts/schemas; implementation uses an isolated managed worktree.

| Artifact family | Consumer | Decision |
| --- | --- | --- |
| request spec, candidate ledger, evidence packets, coverage, discovery errors/manifest | corpus resume, review, hash validation | retain exact layout and hash contracts |
| review decisions, reviewed candidates, selected papers, selection manifest/binding | acquisition, manual import, resume | retain exact layout and immutable bytes |
| acquisition/full-text/evidence ledgers and phase manifests | resume, evidence import | retain |
| research plan, graph, candidate snapshot, research-run | discovery and review | retain as authoritative discovery state; do not duplicate in reports |
| research-manifest, nearest-work matrix | human tabular views | merge as optional papers.csv for new runs |
| evidence-map, gap-analysis, claim coverage | human evidence presentation | one report.md; optional CSV tables; old runs retain old reports |
| pending-metadata/review/research/evidence and manual/retry CSV | human action | new nonempty-only queues where not hash-bound; null path for absent queue; remove only known generated stale files on resume |
| author-discovery.json and audit.json | machine result | retain |
| author/audit CSV | spreadsheet export | opt-in --export-csv; retain report.md summary |
| paper-manifest.csv | human delivered inventory | retain in this release for existing integrations; changing it is unnecessary to remove duplicate reports |

### Task 1: P1 research lifecycle

Files: research/delivery.py, workflow.py, evidence_workflow.py, review.py; tests/unit/test_research_*.py, tests/integration/test_research_cli.py. Controller owns cli.py wiring.

- [x] Write failing behavior tests: discovery creates only plan/graph/candidates/run state; no evidence or gap report. New evidence run writes report.md, optional papers.csv and claim-coverage.csv only when requested; no second candidate snapshot/run/graph in reports. Partial reports disclose unresolved claims and pending papers. Non-gap briefs have no gap conclusion section.
- [x] Add output_version=2 to new research-run, without changing candidate or selection identity. Missing output_version means legacy output behavior on resume.
- [x] Add export_csv=False to evidence entrypoint and expose optional report paths without fake files. Preserve legacy report generation on old runs. Keep research-plan.json as search provenance.
- [x] Retain all machine manifests and validation; omit empty human queues for new runs, preserving legacy empty-queue expectations for legacy runs.
- [x] Run focused tests, verify legacy recovery and review hash regression; report exact CLI wiring required to controller.

### Task 2: P2 optional exports and queues

Files: library/audit.py, library/update.py, author_discovery.py, library_cli.py, acquisition/corpus.py; tests/test_author_discovery.py, test_library_management.py and focused unit/integration tests. Controller owns cli.py and capability_cli.py wiring.

- [x] Write failing tests for default author/audit output (JSON+report, no CSV), --export-csv opt-in, no empty/stale manual queue, and acquisition queue disappearance after successful recovery.
- [x] Add export_csv=False to author discovery/audit and relevant library CLI options; preserve hashes, raw citations, plans and backup behavior. Existing update internal audit need not export CSV.
- [x] Retain paper-manifest.csv and acquisition state/binding. Empty new manual/retry CSV paths become None and manifest values null; tolerate old runs' empty queue files, clear only fixed generated CSVs.
- [x] Inspect all consumers and adjust optional-path annotations. Controller integrates outer CLI null paths.
- [x] Run focused recovery, manual import, library and author tests; report signatures/wiring.

### Task 3: P3 explicit source coverage

Files: new source_catalog.py and focused tests; skill references/sources.md for source evidence. Controller wires `arp sources --spec <corpus.yaml>` and standalone `arp sources` to JSON stdout before constructing publisher services.

- [x] Write failing tests for catalog diagnostics: ACL and IJCAI official-index capability; IEEE journal Crossref ISSN with no official enumerator; ACM conference missing collection DOI remains incomplete; exact collection DOI enables Crossref enumeration but never implies upstream completeness; unsupported publisher acquisition explicit; all requests retain venue/year identity.
- [x] Implement a small offline catalog and describe_sources(spec=None) returning JSON-serializable source capabilities and per-slice diagnostics. Reuse VenueSpec/CorpusSpec parsing and real provider support predicates; avoid broad publisher-name guesses and no network or credentials.
- [x] Distinguish planned capability, live observed coverage, official artifact acquisition maturity and source-relative completeness. API failures in real runs remain existing diagnostics.
- [x] Document official source URLs and scope limits for existing adapters; no unverified new provider or claimed live certification.
- [x] Run focused tests and provide CLI integration details.

### Task 4: P4 entrypoint and documentation

Files: cli.py, capability_cli.py, SKILL.md, README.md, README.zh-CN.md, references/*.md, examples/*.md and input templates as needed.

- [x] Wire optional evidence exports, source catalog, and optional paths; add CLI integration behavior tests first.
- [x] Rewrite skill to three main routes and advanced references, preserving trust/evidence/access requirements. Initial baseline agents failed upstream; the revised skill passed independent agent consumption checks for DOI, corpus, gap, author and library requests.
- [x] Combine Related Work/gap recipes into one research recipe with task-dependent output; keep former links as short compatibility pointers. Keep advanced chapters separately.
- [x] Rewrite README output table by workflow/stage, distinguish authoritative state/report/optional export, and update all stale file expectations. Explain source-relative coverage and venue inventory.
- [x] Run skill validation, document link checks and CLI help/smoke.

### Task 5: review, release and public verification

- [x] Review all task diffs against requirements and execute failure-path tests. Resolve material findings before release.
- [x] Update version to 0.6.0, lockfile, both READMEs, changelog and runtime pin. Run pytest/Ruff, Node/PowerShell suites, build thin skill/wheel, validate exact digest and isolated installed runtime.
- [ ] Commit on codex branch, fast-forward source main after confirming remote unchanged; preserve original checkout edits. Push main, require green CI, tag exact commit v0.6.0 and publish matching wheel/ZIP/SHA256SUMS and release notes.
- [ ] Confirm three-platform public release install workflow and default-branch install. Record actual evidence and limitations; never replace already published asset bytes.

## Progress

- [x] P0 baseline and artifact-consumer inventory.
- [x] P1 research lifecycle.
- [x] P2 optional exports and queues.
- [x] P3 source inventory and per-venue diagnostic.
- [x] P4 routing and documentation.
- [ ] Committed, pushed, published and public-install verified.

## Pre-publication verification

Implementation P0–P4 is complete. Independent review found no high/medium findings after 121 focused checks and an additional legacy end-to-end recovery with unchanged frozen hashes. Ruff, Node (61 tests), three Windows PowerShell suites, source/exported skill validation, Markdown links and isolated wheel bootstrap passed. The isolated skill exercised help/version/sources/schema/config/doctor, author optional CSV, library audit/import/apply/rollback and raw BibTeX bytes. No new live publisher/institution validation is claimed. Remote CI, tag publication and public installation are the remaining external gates and are recorded by the v0.6.0 release and Actions runs.
