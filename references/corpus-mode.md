# Corpus mode

Use this reference for venue/topic/year/count collection tasks, including task files and role-scoped assignments.

## Normalize the request

Create a `CorpusSpec` conforming to `schemas/corpus-spec.schema.json`. Capture:

- minimum, preferred, and maximum totals;
- exact venue names, aliases, type, and optional ISSN/ISBN;
- included and prioritized years;
- included and excluded publication types or tracks;
- positive topics, synonyms, and exclusion concepts;
- group, venue, year, and recent-window quotas;
- output profile, numbering, PDF/BibTeX requirements, and explicit Markdown choice.

Natural language is the usual input. A DOCX, Markdown, TXT, CSV, DOI list, or URL list is only an adapter. If the file contains several people or sections, use a `scope_selector` derived from the user's instruction and preserve the extracted constraints in the run provenance.

## Discover and screen

Use Crossref, OpenAlex, and Semantic Scholar only to discover candidates and graph relationships. Preserve the source, query, record ID, and fields actually observed. Do not copy their citation-style output into `citation.bib`.

Apply hard gates before semantic relevance:

1. venue or proceedings identity;
2. year/date range;
3. publication type and track;
4. DOI/version identity;
5. explicit topic exclusions.

Auto-accept only when the hard gates pass, title and abstract evidence are available, the semantic match is high confidence, and one canonical publisher record is identified. Put boundary cases in `pending-review.csv` with concrete reasons. Reject known wrong tracks even if their titles look relevant.

Satisfy group minimums before filling the remaining preferred total. Stop at the preferred total. If the minimum cannot be met from high-quality candidates, report `shortfall`; never lower thresholds to fill a quota.

Run discovery as its own phase:

```powershell
uv run --project $skill arp discover corpus --spec <job.yaml> --output <discovery-run>
```

Discovery produces:

- `candidates.jsonl`: every merged candidate, observed evidence, decision, and reason;
- `selected-papers.jsonl`: only the deterministic high-confidence selection and its reserved delivery paths;
- `pending-review.csv`: semantic boundary cases that are not selected;
- `discovery-errors.jsonl`: sanitized provider and page diagnostics;
- `selection-manifest.json`: the normalized spec, counts, provider coverage, shortfalls, and SHA-256 of the frozen list.

It does not resolve publisher artifacts or write PDF, BibTeX, acquisition, manual, or retry files. Provider failure may reduce coverage and produce a named shortfall; it never creates a manual-download row because no acquisition has occurred.

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

`candidates.jsonl` is an auditable candidate ledger, not a citation library. `pending-review.csv` contains only semantic decisions; acquisition failures never enter it. `manual-download.csv` contains only frozen selections that the user can retrieve from the official page after automated acquisition finishes.

Import a manual pair with the immutable selection identity:

```powershell
uv run --project $skill arp manual-fetch `
  --selection <discovery-run\selection-manifest.json> --key <selection-id> `
  --output <delivery-root> --watch <download-directory>
```

This mode trusts neither editable CSV values nor filenames. It verifies the frozen list, official identity, PDF, and raw publisher BibTeX before filling the reserved paths. Do not add a source-specific shortcut.
