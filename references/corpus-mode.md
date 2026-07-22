# Corpus mode

Use this reference for venue/topic/year/count collection tasks, including task files and role-scoped assignments.

## Normalize the request

Create a `CorpusSpec` conforming to `schemas/corpus-spec.schema.json`. Capture:

- minimum, preferred, and maximum totals;
- exact venue names, aliases, type, optional venue-specific years, optional ISSN/ISBN, and optional Crossref collection DOI values;
- included and prioritized years;
- included and excluded publication types or tracks;
- positive topics, synonyms, and exclusion concepts;
- group, venue, year, and recent-window quotas;
- output profile, numbering, PDF/BibTeX requirements, and explicit Markdown choice.

Natural language is the usual input. A DOCX, Markdown, TXT, CSV, DOI list, or URL list is only an adapter. If the file contains several people or sections, use a `scope_selector` derived from the user's instruction and preserve the extracted constraints in the run provenance.

## Enumerate, enrich, and prepare evidence

Enumerate every requested venue/year slice before topic screening. Use an official proceedings index where supported and a paginated Crossref venue/date stream as the generic source. ISSN identifies journals. For a Crossref-indexed proceedings collection, set `collection_doi` to the parent DOI values; the provider enumerates records through Crossref's exact `alternative-id` filter. A conference declared with `kind: conference` and no official provider or collection DOI is reported as incomplete instead of treating fuzzy title search as exhaustive. OpenAlex and Semantic Scholar may enrich or expand candidates, but they do not establish final citation artifacts. Preserve the source, record ID, observed fields, coverage state, and sanitized request provenance.

Apply hard gates before semantic relevance:

1. venue or proceedings identity;
2. year/date range;
3. publication type and track;
4. DOI/version identity;
5. explicit topic exclusions.

The deterministic lexical prefilter is high recall and produces review signals only. It never rejects a hard-gate-passing candidate for lacking an exact phrase. Normalize case, Unicode separators, hyphens, plurals, and common inflections. A candidate without an abstract goes to `pending-metadata.csv`; keywords are optional.

Discovery and selection are separate phases. Discovery prepares immutable evidence. Codex then decides semantic relevance from title and abstract; keywords are optional and full text is not required. Selection is frozen only after those decisions pass hash and schema validation.

Run discovery as its own phase:

```powershell
uv run --project $skill arp discover corpus --spec <job.yaml> --output <discovery-run>
```

Discovery produces:

- `request-spec.json`: the normalized request used by this run;
- `coverage.jsonl`: complete, partial, or failed state for each provider venue/year slice;
- `candidates.jsonl`: every merged candidate, hard-gate result, metadata state, and prefilter signals;
- `evidence-packets.jsonl`: immutable review evidence with candidate ID and SHA-256;
- `pending-metadata.csv`: candidates that still lack title or abstract evidence;
- `discovery-errors.jsonl`: sanitized provider and page diagnostics;
- `discovery-manifest.json`: request hash, counts, provider coverage, and artifact names.

It does not write `selected-papers.jsonl`, resolve publisher artifacts, or write PDF, BibTeX, acquisition, manual, or retry files. Retry the same output directory when coverage is partial; completed slices are checkpointed and candidates are merged by stable identity.

## Review and freeze

Read `evidence-packets.jsonl` and write `review-decisions.jsonl`. Each record must contain:

- `candidate_id` and the unchanged `evidence_hash`;
- `decision`: `accept`, `reject`, or `pending`;
- `matched_topics` and `evidence_fields` used by the decision;
- a concrete `reason`;
- `reviewer: codex` and a stable `rule_version`.

Use title and abstract for the decision; keywords are optional. Do not require publisher login or full text. Missing abstracts remain pending. Then import decisions:

```powershell
uv run --project $skill arp review corpus `
  --run <discovery-run> --decisions <review-decisions.jsonl>
```

The importer rejects unknown/duplicate IDs, changed hashes, invalid enums, unsupported evidence fields, and acceptance without ready metadata. It applies group and recent-window quotas to accepted candidates, stops at the preferred total, and writes `reviewed-candidates.jsonl`, `pending-review.csv`, `selected-papers.jsonl`, and `selection-manifest.json`. Named shortfall classes distinguish coverage, evidence, review, and quota work. Never lower semantic criteria to fill a quota.

## Acquire and deliver

Acquire the frozen selection explicitly:

```powershell
uv run --project $skill arp acquire corpus `
  --selection <discovery-run\selection-manifest.json> --output <delivery-root> `
  --defer-host <publisher.example>
```

The acquisition phase verifies the selected-list hash before any publisher request. It routes every frozen record through the same publisher adapters used by `fetch`; it cannot discover extra papers or change semantic decisions. Delivery is complete only when both files pass:

- official PDF validation and SHA-256 recording;
- official raw BibTeX parse and metadata comparison.

Reserved numbering and relative paths are assigned when selection is frozen, so automatic and manual acquisition target the same slots. Reuse the global registry and artifact hashes for interrupted-run recovery. A rerun skips a delivered item only when all three recorded paths and PDF, BibTeX, and provenance hashes still match.

`--defer-host` is a repeatable, run-scoped control for temporarily disabling publisher contact without changing the selection. It accepts exact hostnames only and compares them case-insensitively. A matching item with no verified prior delivery becomes `manual_required` with `access_required`; a verified prior delivery is still reused. This is publisher-neutral and must not be implemented as a venue-specific selection filter.

Acquisition writes one durable state per selected paper to `acquisition-manifest.jsonl`:

- `delivered`: the official PDF and raw publisher BibTeX are verified;
- `manual_required`: authorized user interaction or an unsupported safe adapter is required;
- `retryable`: a transient network or rate-limit failure may be retried;
- `contract_error`: the official page or returned artifact violates its contract.

It also writes `manual-download.csv`, `retryable-downloads.csv`, and `delivery-manifest.json`. No outcome removes a record from `selected-papers.jsonl`. The delivered count, not the discovered count, determines acquisition completion.

## Review output

`candidates.jsonl` is an auditable candidate ledger, not a citation library. `pending-metadata.csv` contains discovery evidence gaps. `pending-review.csv` contains unresolved semantic decisions after import; acquisition failures never enter it. `manual-download.csv` contains only frozen selections that the user can retrieve from the official page after automated acquisition finishes.

Import a manual pair with the immutable selection identity:

```powershell
uv run --project $skill arp manual-fetch `
  --selection <discovery-run\selection-manifest.json> --key <selection-id> `
  --output <delivery-root> --watch <download-directory>
```

This mode trusts neither editable CSV values nor filenames. It verifies the frozen list, official identity, PDF, and raw publisher BibTeX before filling the reserved paths. Do not add a source-specific shortcut.
