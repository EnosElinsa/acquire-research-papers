# Explicit book chapters

Input: source book PDFs and each chapter's native publisher BibTeX export. Copy [chapter-map.json](inputs/chapter-map.json) and populate its array with explicit records. An empty map requests no chapters. Every row needs `source` (relative book path), `doi`, `title`, `year`, `start_page`, `end_page`, and preferably `bib_file` (relative native export path). Page numbers are 1-based inclusive PDF pages, not printed page labels.

Example shape after replacing every placeholder with verified data:

```json
[
  {
    "source": "book.pdf",
    "doi": "<actual chapter DOI>",
    "title": "<actual chapter title>",
    "year": 2026,
    "start_page": 1,
    "end_page": 12,
    "bib_file": "chapter.bib"
  }
]
```

The year/pages above illustrate types only and are not suggested extraction ranges. Independently verify chapter identity and exact PDF pages. Then run:

```text
arp library import <incoming-books> --destination <library> --chapters <work>/chapter-map.json --output <work>/chapter-plan.json
arp library apply --plan <work>/chapter-plan.json
arp library audit <library> --metadata <work>/empty-metadata.json --output <work>/chapter-audit
```

Before apply, inspect chapter DOI/title/year, source-book hash, citation hash, inclusive page range and derived provenance. Copy [empty-metadata.json](inputs/empty-metadata.json) for the offline final audit. The source book is retained. Native citation bytes remain native; legacy inline `bib` text remains explicitly `manual_import_text`.

Expected output: a reviewable chapter plan, derived PDFs with explicit source/range provenance, untouched source books, preserved BibTeX bytes, backups and apply journal.

Recovery: same-plan apply resumes/idempotently verifies. Roll back with `arp library apply --plan <work>/chapter-plan.json --rollback` if hashes match; later changes require a new audit/plan. Correct identity or page errors in a new map/plan before mutation.

Limits: never infer chapter DOI/title from a table of contents alone, guess PDF offsets, fabricate BibTeX, or upgrade a derived chapter to independently fetched official PDF provenance. See [library mode](../references/library-mode.md).
