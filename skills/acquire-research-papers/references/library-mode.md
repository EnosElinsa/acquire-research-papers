# Existing publication libraries

Use `python <skill-directory>/scripts/arp.py` wherever examples say `arp`. Keep report/staging output outside the library whenever possible; `update` requires a separate output directory.

```text
arp library audit <library-directory> --output <audit-directory>
arp library update <library-directory> --verify-only --output <verification-directory>
arp library update <library-directory> --output <staging-directory>
arp library update <library-directory> --watch <downloads-directory> --timeout 120 --output <staging-directory>
arp library import <incoming-directory> --destination <library-directory> --output <plan.json>
arp library organize <library-directory> --output <plan.json>
arp library apply --plan <plan.json>
arp library apply --plan <plan.json> --rollback
```

Audit records PDF/BIB hashes, DOI/title evidence, pairing confidence, invalid/missing/ambiguous items, exact DOI duplicates, and byte duplicates. Existing publisher delivery bundles may pair through matching provenance hashes even when named `paper.pdf` and `citation.bib`. Unidentified or ambiguous pairs are skipped by import/organize and need review.

Audit emits `audit.json` and `report.md`, plus `manual-download.csv` only when action is pending. Add `--export-csv` to `library audit` for `audit.csv`. Resolved queues and unrequested generated CSV views are removed on rerun; keep hand edits under other filenames. Read `citation_source`: provenance-confirmed publisher exports remain native publisher artifacts; hand-imported citations remain `manual_import` unless evidence establishes their source. Neither audit nor rename upgrades citation provenance.

## Publication versions and dates

Compare `citation_status`, `local_version`, and overall `publication_status` separately. A citation with current volume/issue/pages does not establish the version of its PDF. PDF early-access evidence can make an otherwise current citation pair stale. Exact official PDF-byte hashes can establish a publisher-byte match; absent evidence stays `requires_verification` or `unknown`.

Issue/print publication dates are distinct from online-publication dates. A year-only field does not prove either. Positive issue date, volume, and page/article placement can establish finalization; missing fields never prove finality. Crossref publisher-deposited registry metadata is labeled `discovery_registry` and may yield `possible_update`, not proof of current publisher PDF bytes. Bounded public publisher metadata lookup may improve evidence when accessible. ScienceDirect pages are never automatically requested or automated; use permitted registry/API evidence or explicitly supplied publisher metadata and manual downloads.

For deterministic offline work, pass `--metadata <metadata.json>`. This is a DOI-keyed object of review-provided evidence; `{}` disables all metadata lookup. Example:

```json
{
  "10.1234/example": {
    "doi": "10.1234/example", "title": "Full Official Title with GPU and iPhone",
    "venue": "Official Journal", "venue_abbreviation": "OJ",
    "issue_date": "2026-03", "online_date": "2025-11-20",
    "volume": "4", "issue": "3", "pages": "10-21",
    "evidence_kind": "publisher_metadata", "source": "Reviewed publisher export"
  }
}
```

Label registry evidence as `discovery_registry`; never present it as native citation provenance or official PDF verification. Optional `pdf_sha256` is meaningful only when it comes from the official publisher artifact independently verified for that DOI.

## Stage, review, apply

`update` stages replacement pairs through the ordinary official acquisition adapter and generates a hash-bound plan. It does not overwrite the library. `--verify-only` performs no acquisition. The bounded optional watcher snapshots the directory at startup, accepts only new or changed user-downloaded pairs after consecutive stable hashes, maintains a single queue, and performs zero browser automation. Still-early-access PDFs or pairs missing/mismatching the current placement evidence remain pending. Use explicit import for files downloaded before watcher startup. ScienceDirect download actions remain with the user.

Import copies and leaves incoming files intact. Organize moves verified pairs. Filenames use full supplied publication titles in Title Case while preserving acronyms, mixed case, and CJK, then venue abbreviation/year. Collisions and long paths receive deterministic digest suffixes. Cite bytes, BOM, encoding, and line endings are retained; only parsing uses UTF-8/UTF-8-SIG or GB18030.

Review each `plan.json` action, source/target path, DOI, hash, citation-source evidence, and skipped-item diagnostic. Apply checks the plan digest, source hashes, destination hashes/collisions, and path boundaries before mutation; it keeps backups and an operation journal. Reapplying the same completed plan is idempotent. Interrupted prepared operations can resume. Rollback refuses changed outputs or corrupt backups instead of destroying later edits. Keep the plan and backups until verified. A per-library OS advisory lock refuses concurrent apply operations and releases automatically when the process exits. The atomic no-clobber write path requires filesystem hard-link support; unsupported filesystems fail with diagnostics.

Schemas: [library-plan](../schemas/library-plan.schema.json) and [library-audit](../schemas/library-audit.schema.json). These records are separate from frozen corpus/research manifests and never modify their hashes.

## Explicit book chapters

`library import --chapters <chapter-map.json>` additionally derives chapters only from an explicit identity and 1-based inclusive PDF page map. Each row requires `source`, `doi`, `title`, `year`, `start_page`, `end_page`, and preferably `bib_file` pointing to the native publisher export relative to the source directory. The native file retains its exact BOM, UTF-8/GB18030 bytes, and line endings. Ingestion validates DOI/title/year and apply rechecks the original citation hash. Legacy `bib` text is accepted as `manual_import_text` with explicit provenance; it is not upgraded to a native export. Retain the source book. The plan includes source-book hash, chapter identity, page range, and derived provenance; never infer chapter identity from a TOC or silently replace a whole book with an extracted chapter.
