# Extensible Corpus Discovery and Acquisition Design

Date: 2026-07-21
Status: Approved for specification by the user

## Context

Corpus mode currently performs discovery, screening, selection, and acquisition in one workflow. The default application discovers only through Crossref, and `CorpusWorkflow.run` immediately sends selected candidates to an acquirer. This coupling creates three problems:

- a discovery run cannot be inspected or reused before network and access-sensitive downloads begin;
- an acquisition failure is mixed into semantic review output even though it does not change whether the paper belongs in the corpus;
- adding an official proceedings index requires another special search function rather than a stable source contract.

The student 2 corpus exposed these limitations. Crossref returned many records from the requested venues but no abstracts, so the conservative screening gate correctly produced no automatic selections. Official indexes such as ACL Anthology and IJCAI proceedings expose title, abstract, keywords or track metadata, but the skill has no general way to use official index evidence during corpus discovery. The current planner also declares recent-window, group-maximum, and numbered-delivery settings in the schema without fully enforcing them.

This design separates paper discovery from paper acquisition and makes the boundary a durable, auditable selection list. It also introduces an extensible provider protocol, completes the generic quota semantics needed by the current corpus, and makes numbered delivery a configuration-driven layout rather than a task-specific script.

## Goals

1. `discover corpus` performs discovery, evidence collection, screening, and quota-aware selection only. It never downloads a PDF or BibTeX file.
2. Discovery writes a frozen `selected-papers.jsonl` list plus a manifest. Acquisition consumes that exact list and never adds, removes, or semantically reclassifies papers.
3. Discovery sources implement one typed provider protocol. Conference indexes, journal indexes, and scholarly metadata APIs can be added without changing the coordinator, screener, planner, downloader, or CLI workflow.
4. Existing Crossref, OpenAlex, and Semantic Scholar clients fit the same provider boundary. ACL and IJCAI are the first official-index implementations, not special cases in the core.
5. Acquisition automatically downloads and verifies every supported selected paper. Papers that require user action remain selected and are written to an actionable manual-download queue.
6. Recent-window minimums, group minimums and maximums, global targets, year priority, and numbered delivery are deterministic and enforced from `CorpusSpec`.
7. Publisher PDF and raw publisher BibTeX remain the only deliverable pair. Discovery metadata never substitutes for final citation artifacts.

## Non-goals

- This change does not bypass publisher authentication, CAPTCHA, OTP, WAF, rate limits, or page contracts.
- It does not automate ScienceDirect pages or organization login. ScienceDirect remains a manual publisher-download workflow.
- It does not make Crossref, OpenAlex, Semantic Scholar, or generated BibTeX a final citation authority.
- It does not add venue, student, assignment-document, or topic-specific branches to the core pipeline.
- It does not introduce a universal CSS-selector configuration language. Each official website keeps a small explicit parser because page contracts, track rules, and approved hosts require code-level review and fixture tests.
- It does not promise that every selected paper can be delivered automatically. Incomplete delivery is reported without changing the frozen selection.

## Approaches considered

### Independent per-venue search functions

Adding `AclSearcher`, `IjcaiSearcher`, and later one function per venue would be the smallest immediate edit. It would leave source activation, errors, pagination, merging, and provenance inconsistent and would require core changes for every new venue. This approach is rejected.

### Fully declarative web-scraping configuration

A data file containing URL templates and CSS selectors would make simple indexes quick to add. It would be fragile for multi-page indexes, track boundaries, dynamic pages, redirect policies, and source-specific identity checks. It would also make security-sensitive host and authentication behavior too easy to broaden accidentally. This approach is rejected.

### Typed provider protocol with explicit adapters

The selected approach uses a common provider interface and coordinator, shared HTTP and normalization utilities, and small explicit source adapters. Stable values such as aliases, supported years, URL templates, and track labels may be data-driven inside an adapter. Parsing and identity rules remain code with fixtures. This balances extension cost, auditability, and page-contract safety.

## Architecture

The corpus path is split into two independently runnable workflows:

```text
CorpusSpec
    -> CorpusDiscoveryWorkflow
    -> candidates.jsonl + selected-papers.jsonl + selection-manifest.json
    -> CorpusAcquisitionWorkflow
    -> verified artifacts + acquisition ledger + manual/retry queues
```

The discovery workflow owns evidence and semantic decisions. The acquisition workflow owns publisher routing, access attempts, artifact validation, and delivery status. The selection manifest is the only handoff between them.

### Discovery request and provider protocol

Add typed discovery models under `discovery/`:

- `DiscoveryRequest`: normalized venues and aliases, venue kind, identifiers, included and prioritized years, included and excluded publication types, positive and negative topic terms, target limits, and the source query budget derived from `CorpusSpec`.
- `DiscoveryCapabilities`: provider ID, source class (`metadata_api` or `official_index`), supported venue scopes, supported year scopes, available evidence fields, and whether credentials are required.
- `DiscoveryProvider`: exposes `capabilities()` and `discover(request) -> DiscoveryBatch`.
- `DiscoveryBatch`: candidates plus zero or more sanitized `DiscoveryDiagnostic` records.
- `DiscoveryDiagnostic`: provider ID, optional venue and year, phase, URL, error code, retryability, and sanitized message.

`DiscoveryProvider` is venue-agnostic at the coordinator boundary. A provider decides whether it supports all or part of a request through its capabilities. The coordinator passes only supported venue/year slices to it. An unsupported slice is normal and is not recorded as an error.

Existing query-based clients are adapted through an `ApiDiscoveryProvider` wrapper rather than retaining a second coordinator interface. An official source implements the same protocol but may enumerate an index and then fetch detail pages. The registry contains provider instances; adding a provider requires a new adapter and registry entry, not a branch in `CorpusDiscoveryWorkflow`.

### Initial providers

The first implementation registers:

- Crossref through the metadata-API wrapper;
- OpenAlex when its API key is configured;
- Semantic Scholar when it is configured and available;
- ACL Anthology as an official-index provider;
- IJCAI proceedings as an official-index provider.

ACL and IJCAI establish the official-index contract because their official pages currently provide the evidence missing from Crossref. ACL accepts Annual Meeting long-paper IDs only when the requested publication type requires long or regular papers. IJCAI parses the requested track and accepts Main Track only for a main-track corpus. These rules live inside those adapters. The coordinator contains no ACL or IJCAI names, URLs, identifiers, or track rules.

Future KDD, journal, or publisher indexes use the same protocol. A provider blocked by a WAF reports a diagnostic; the coordinator continues other providers and reports any resulting shortfall.

### Candidate evidence and identity merging

`CandidateMetadata` remains the normalized candidate record and is extended with keywords, track, source records, and field-level provenance. A source records only fields it actually observed. The final candidate ledger therefore distinguishes, for example, a Crossref title from an official-index abstract.

The coordinator merges records using this identity order:

1. normalized DOI;
2. canonical official landing URL;
3. a normalized title, year, and venue identity when neither DOI nor URL exists.

Merging unions evidence fields and source records, preserves every source identifier in provenance, and keeps the highest-quality non-empty value according to a fixed authority order: official venue record, then metadata API record. Conflicting DOI, year, or venue identities are never silently merged; they become separate candidates with a diagnostic or pending-review reason. Screening occurs once after all providers have completed, so an abstractless API record cannot mask official abstract evidence for the same paper.

### Screening and selection

Screening is a pure operation over discovered metadata. It performs no publisher requests and has no acquisition dependency.

Hard gates run before relevance scoring:

1. venue identity;
2. year or date range;
3. publication type and track;
4. DOI/version identity consistency;
5. explicit exclusion concepts.

Automatic acceptance still requires title and abstract evidence, a canonical DOI or official page, and the configured high-confidence relevance threshold. Keywords supplement title and abstract evidence but do not replace the abstract requirement. Boundary cases remain in `pending-review.csv`; rejected and not-selected records remain auditable in `candidates.jsonl`.

The planner applies constraints deterministically. It first sets the planned total to the preferred total capped by the global maximum. If the high-confidence pool cannot reach that total, it uses the largest feasible total and still requires the global minimum:

1. rank candidates by configured year priority, publication date, relevance score, and stable identity;
2. satisfy group minimums in specification order from unused ranked candidates while respecting every applicable group maximum;
3. satisfy the recent-window minimum count, computed as `ceil(planned_total * minimum_ratio)`, while respecting group maximums;
4. fill toward the preferred total in rank order while respecting the global maximum and group maximums;
5. validate global minimum, every group minimum, every group maximum, and the recent-window minimum over the final selection.

Candidates may match more than one group and count toward every matching group. Group order is therefore part of the declared deterministic policy. If filling constraints produces fewer records than the original planned total, the recent-window count is recomputed against the final total before validation. A group whose minimum exceeds its maximum is invalid input. When the ranked pool cannot satisfy a constraint, the planner emits a named quota shortfall and never lowers relevance or evidence thresholds.

### Frozen selection contract

Discovery writes the following files atomically before returning:

- `candidates.jsonl`: every merged candidate, evidence provenance, decision, and reasons;
- `selected-papers.jsonl`: only high-confidence selected papers, in deterministic delivery order;
- `pending-review.csv`: candidates requiring a human semantic decision;
- `discovery-errors.jsonl`: sanitized provider failures and page-contract diagnostics;
- `selection-manifest.json`: schema version, normalized spec snapshot, spec SHA-256, selected-list SHA-256, provider coverage, counts, quota results, and relative output paths;
- `corpus-manifest.json`: discovery-phase summary retained for CLI and backward-readable reporting.

Each selected record contains a stable selection ID, logical ordinal, title, authors, DOI, official URL, venue, venue alias, publisher or archive identity when known, year, publication date, publication type, track, discovery evidence summary, and relative PDF/BibTeX delivery paths. The abstract and keywords remain in the selection record for audit but are never copied into citation files.

The selection list is immutable input to acquisition. `CorpusAcquisitionWorkflow` verifies the selected-list hash from `selection-manifest.json` before doing work. Direct edits cause an input-integrity error. A later user-review import must create a new versioned selection snapshot rather than mutate an existing snapshot; implementing interactive review decisions is outside this design's acquisition path.

## CLI and phase behavior

The commands become explicit:

```powershell
uv run arp discover corpus --spec <job.yaml> --output <discovery-run>
uv run arp acquire corpus --selection <discovery-run\selection-manifest.json> --output <delivery-root>
```

`discover corpus` never accepts an acquirer and never writes PDF, BibTeX, acquisition, or manual-download artifacts. It returns `planned` or `shortfall` based on the selected corpus and quota results.

`acquire corpus` reads only the frozen selection. It may refresh publisher metadata needed to validate a page, but it cannot discover extra papers or change semantic decisions. Rerunning the same command is the resume operation: verified delivered pairs are skipped by registry identity and hashes, retryable records are attempted again, and manual-required records remain queued unless the verified pair has since been imported.

The existing single-paper `fetch` and `manual-fetch` commands remain available. The corpus acquisition command uses the same acquisition router and publisher adapters rather than source-specific download shortcuts.

For a queued manual item, `manual-fetch` also accepts the frozen selection and selection ID:

```powershell
uv run arp manual-fetch --selection <selection-manifest.json> --key <selection-id> `
  --output <delivery-root> --watch <download-directory>
```

This mode derives the expected identity and reserved relative paths from the frozen selection. It does not trust editable values from `manual-download.csv`.

## Acquisition workflow

For each selected record, acquisition routes the canonical DOI or official landing page through the existing adapter registry. A record reaches `delivered` only after the official PDF and raw publisher BibTeX both pass identity validation and their hashes and provenance are recorded.

Acquisition outcomes are separate from selection decisions:

- `delivered`: both official artifacts are verified and committed;
- `manual_required`: automatic acquisition is unsafe, unsupported, publisher-manual-only, or blocked by access that the user can complete on the official page;
- `retryable`: a sanitized transient network or rate-limit failure can be retried without user download;
- `contract_error`: the official page or returned artifact does not meet the adapter contract and must not be accepted.

No outcome removes a paper from `selected-papers.jsonl`. Acquisition writes:

- `acquisition-manifest.jsonl`: one durable state record per selected paper;
- `manual-download.csv`: actionable selected papers requiring user download;
- `retryable-downloads.csv`: transient failures suitable for another automated run;
- `delivery-manifest.json`: delivered, manual, retryable, contract-error, and quota-completion counts;
- the configured artifact tree containing only verified pairs and provenance.

`manual-download.csv` contains selection ID, ordinal, title, DOI, canonical official URL, publisher host, reason, sanitized message, target relative PDF path, and target relative BibTeX path. The user downloads from that official page. `manual-fetch` then watches or imports the two local files, verifies them against the selected identity, and commits them to the reserved target paths. It never trusts a filename alone.

Transient failures remain in the acquisition ledger and retry queue rather than being misclassified as semantic review. Contract errors remain visible and do not become delivered or silently fall back to a mirror.

## Generic delivery layout

Delivery layout is derived entirely from `CorpusSpec.delivery` and selected metadata. No task- or venue-specific renaming script is permitted.

Venue records gain optional `short_name` and `publisher` fields for display and layout. They are descriptive configuration, not matching aliases. For `profile: numbered`, `naming_template` is a safe relative path template supporting these fields:

- `{publisher}`: normalized publisher or official archive label;
- `{venue}` and `{venue_short}`;
- `{year}`;
- `{number}`: logical ordinal within the rendered parent folder;
- `{ext}`: `pdf` or `bib`.

The student 2 layout can therefore be expressed as `2026.7.18 {publisher} {venue_short}/{number}.{ext}` without code changes. The date is ordinary literal template text rather than a task-specific field. Numbering starts at one and is contiguous within each rendered parent folder. Logical ordinals and relative paths are assigned when the frozen selection is created so automatic and manual acquisition target the same locations. A path is considered delivered only after its PDF/BibTeX pair is verified. A partial run may show reserved, documented slots; a completed corpus has no numbering gaps.

Template validation rejects absolute paths, parent traversal, empty filenames, Windows-invalid components, reserved device names, and collisions. Both extensions for one selection must render to the same parent and base number. Generic delivery remains the default when no numbered profile is requested.

## Error handling and security

Discovery and acquisition errors are intentionally distinct.

- A discovery-source error records provider coverage loss and may cause a selection shortfall. It never creates a manual-download row because no paper has yet been selected for acquisition.
- An acquisition error preserves the selected record and becomes delivered, manual-required, retryable, or contract-error state.
- One provider, venue, year, or paper failure does not stop unrelated work.
- Empty provider output is valid only when the provider explicitly reports successful coverage. Page-contract drift must not be disguised as an empty result.
- All error records are sanitized. They contain no credentials, API keys, tokens, cookies, browser storage, full page bodies, or sensitive query strings.

Existing publisher boundaries remain unchanged. IEEE credentials are released only to the exact configured institution host, and automation stops on CAPTCHA, OTP, or incomplete login. ScienceDirect remains manual-only. Redirects and artifact URLs stay inside adapter-approved hosts. Discovery URLs never authorize an acquisition host or replace publisher artifact validation.

## Compatibility and migration

`fetch`, `manual-fetch`, research discovery, registry storage, and publisher adapters retain their existing public behavior. Corpus discovery changes intentionally from an implicit one-shot operation to a planning-only command. The old combined `CorpusWorkflow` is split into `CorpusDiscoveryWorkflow` and `CorpusAcquisitionWorkflow`; no compatibility wrapper may silently download during `discover corpus`.

Existing API clients are wrapped behind the new provider protocol before official-index providers are registered. This ensures the extension point is exercised by both general metadata APIs and venue-owned sources. Existing `CandidateMetadata` callers remain source-compatible through defaults for newly added fields where practical.

The corpus-spec schema keeps its current concepts and adds only optional venue `short_name` and `publisher` metadata needed by generic layout templates. Validation is tightened for contradictory target, group, recent-window, missing template fields, and numbered-template values. Selection and acquisition manifests receive their own explicit schema versions so future fields can be added without guessing file semantics.

## Testing strategy

Implementation follows red-green TDD.

### Provider contract tests

A reusable contract suite runs against fake providers and every registered provider adapter. It verifies capability slicing, deterministic results, provenance, diagnostic sanitization, unsupported-scope behavior, and absence of final citation artifacts in discovery output.

Official-index adapters use small frozen HTML fixtures. ACL fixtures cover long versus short/front-matter IDs and inline abstract extraction. IJCAI fixtures cover Main Track boundaries, detail-page abstract and keyword extraction, and page drift. A fake provider for an invented venue proves the coordinator and workflow contain no ACL, IJCAI, conference, or student-specific branch.

### Discovery workflow tests

- metadata API and official-index records with the same DOI merge into one candidate;
- conflicting identities remain separate and auditable;
- title, abstract, and keyword evidence is preserved with field provenance;
- discovery writes and hashes the frozen selected list before returning;
- discovery never calls the acquisition router and produces no PDF or BibTeX;
- one provider failure writes a diagnostic while other providers continue;
- group minimums and maximums, recent-window ratio, year priority, global targets, and named shortfalls are enforced deterministically;
- pending and rejected candidates never enter `selected-papers.jsonl`.

### Acquisition workflow tests

- acquisition accepts a valid selection manifest and rejects a modified selected list;
- only selected records are routed to publisher adapters;
- delivered, manual-required, retryable, and contract-error states remain separate;
- an inaccessible paper enters `manual-download.csv` without stopping later automatic downloads;
- rerunning skips already verified pairs and retries only eligible states;
- manual import verifies PDF/BibTeX identity before filling the reserved target paths;
- numbered templates produce safe, collision-free, contiguous logical slots for an arbitrary fake venue;
- partial delivery never changes the selected list or semantic counts.

### Regression and validation gates

Run the complete Python test suite, Node IEEE tests, PowerShell secret-store tests, Ruff, package validation, and skill validation before implementation commits. Live publisher smoke tests may be performed only within the existing security contracts and are reported separately from deterministic fixture tests.

## Acceptance criteria

1. Running `discover corpus` produces an auditable candidate ledger for every successful provider slice and a frozen selected list without attempting any download.
2. Running `acquire corpus` against that selection attempts every selected paper, downloads and verifies supported pairs, and preserves every undelivered selection in a manual, retryable, or contract-error state.
3. A new fake venue/provider can participate in discovery and acquisition tests without editing the discovery coordinator, screener, planner, acquisition workflow, or CLI command implementation.
4. Crossref, OpenAlex, Semantic Scholar, ACL Anthology, and IJCAI use the same provider boundary; unavailable optional providers do not abort available ones.
5. Automatic acceptance still requires hard gates plus title and abstract evidence. No discovery source provides final BibTeX.
6. Recent-window, group minimum and maximum, global target, and numbered-delivery settings are actually enforced and audited.
7. Manual-download rows contain the official page and reserved target paths needed for the user to complete the pair, and later import verifies both artifacts.
8. Publisher access and credential restrictions are unchanged, and all existing security regression suites pass.
9. The student 2 assignment can be expressed only through a generic `CorpusSpec`; no implementation code contains its role name, topic set, target venue list, or output folder names.
