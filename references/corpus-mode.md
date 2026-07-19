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

## Acquire and deliver

For every auto-accepted or user-approved candidate, route the canonical DOI or official landing page through `fetch`. Delivery is complete only when both files pass:

- official PDF validation and SHA-256 recording;
- official raw BibTeX parse and metadata comparison.

Use stable, gap-free numbering only after pair verification. Reuse the global registry for DOI/title deduplication and interrupted-run recovery. A corpus run without an explicit Markdown request delivers PDF, BibTeX, manifests, and review files only.

## Review output

`candidates.jsonl` is an auditable candidate ledger, not a citation library. `pending-review.csv` contains only decisions requiring human or agent semantic judgment. After review, acquire accepted items through the same verified fetch path; do not add a source-specific shortcut.
