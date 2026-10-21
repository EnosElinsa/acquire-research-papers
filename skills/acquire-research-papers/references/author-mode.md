# Author bibliography discovery

```text
arp discover author --spec <author.json> --output <discovery-directory>
arp discover author --spec <author.json> --records <offline-records.json> --output <discovery-directory>
```

Run these through `python <skill-directory>/scripts/arp.py`. Inputs follow [author-spec.schema.json](../schemas/author-spec.schema.json). A practical specification:

```json
{
  "name": "Ada Example", "orcid": "0000-0002-1825-0097", "dblp": "12/3456",
  "homepage": "https://research.example.org/ada",
  "affiliation": "Example University", "coauthors": ["Alex Example"],
  "date_from": "2024-01-01", "date_to": "2026-12-31",
  "local_dir": "/path/to/existing/library", "max_records": 100
}
```

Supply real identity evidence; example IDs and hosts above demonstrate format only. ORCID/DBLP links scope records to the supplied identity but do not prove every upstream record is correct. Affiliation and coauthors support name matching; name-only, homepage, and database results stay ambiguous without supporting evidence. Do not merge similarly named people automatically.

The production client reads anonymous public ORCID works, DBLP person bibliographies, DOI links on a supplied public homepage, and bounded Crossref author-search records. HTTP requests have finite timeouts and no unbounded retry. Each source reports fetched count, truncation/total when available, skipped configuration, or sanitized errors. Sources vary in coverage; private, unsupported, rate-limited, or missing sources stay explicit. There is no claim of an absolutely complete bibliography.

Normalize and deduplicate exact DOI only. A shared title does not establish identity. Source-scoped records without DOI remain separate. Formal publications, early access, and preprints are grouped explicitly. Link distinct preprint/published records only when an explicit relation establishes that connection; title similarity is not version evidence. Keep online/preprint dates separate from issue/print dates. Filter by issue date first when known, then online/other date with the basis recorded; partial/unknown dates and conflicting sources remain visible for review.

Optional `local_dir` matches exact DOI against local library records and reports paired, BIB-only/PDF-only, or missing. Discovery does not download papers, generate native citations, change the library, or modify corpus/research hashes. Use an explicit acquisition or reviewed library plan afterward.

Default output: `author-discovery.json` and `report.md`; add `--export-csv` for `author-discovery.csv`. Re-running without the flag clears that generated CSV view; [author-discovery.schema.json](../schemas/author-discovery.schema.json) describes the result. Review raw source evidence, identity statuses, date conflicts, group membership, version relations, and coverage limitations before describing the bibliography.

Offline records use a source-keyed object, such as `{"orcid": [{"doi": "10.1234/example", "title": "Example", "issue_date": "2026-03"}], "database": {"error": "offline source unavailable", "records": []}}`. These are discovery records, never publisher citation artifacts.
