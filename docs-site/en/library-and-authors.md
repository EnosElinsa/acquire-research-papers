# Libraries and authors

The examples use `arp` as shorthand for `python <skill-directory>/scripts/arp.py`.

## Local PDF/BibTeX libraries

```text
arp library audit <library-directory> --output <audit-directory>
arp library update <library-directory> --output <staging-directory>
arp library import <incoming-directory> --destination <library-directory> --output <plan.json>
arp library organize <library-directory> --output <plan.json>
arp library apply --plan <plan.json>
arp library apply --plan <plan.json> --rollback
```

Library audits report identities, duplicates, missing/ambiguous pairs, citation placement, and the PDF's independently evidenced version. A current BibTeX record does not prove the PDF is current. Registry metadata stays discovery evidence.

Update stages official pairs; import/organize produce hash-bound plans; explicit apply checks hashes and keeps backups. Raw BibTeX bytes, BOM, encoding, and line endings are preserved. Optional `--metadata` inputs enable offline comparison; `update --verify-only` avoids acquisition. A bounded `--watch` observes user-downloaded ScienceDirect pairs and maintains one queue without automating a browser. See the [library reference](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/library-mode.md).

## Author bibliographies

```text
arp discover author --spec <author.json> --output <discovery-directory>
```

Author specs accept identity IDs, affiliation/coauthors, date range, homepage, and a local library. Public ORCID, DBLP, homepage, and database records retain identity uncertainty and source errors. Exact DOI deduplication, formal/early-access/preprint groups, issue dates primary to online dates, and explicit version relations remain auditable; coverage is never claimed absolutely complete. `--records` supplies offline source evidence. See the [author reference](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/author-mode.md).
