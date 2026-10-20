# Local library update and organization

Input: an existing library, a private work directory, and optionally [empty-metadata.json](inputs/empty-metadata.json) for a network-free first audit. Replace that map only with reviewed DOI-keyed evidence and provenance. Keep work/staging outside the source library.

```text
arp library audit <library> --metadata <work>/empty-metadata.json --output <work>/audit
arp library update <library> --verify-only --output <work>/verify
arp library update <library> --output <work>/staged-update
```

Read audit and update evidence before applying. Distinguish citation placement, local PDF version, issue date, and online date. The update output stages official replacement pairs and a hash-bound plan rather than overwriting the library. For organizing existing verified pairs, run `arp library organize <library> --output <work>/organize-plan.json`. For incoming pairs, run `arp library import <incoming> --destination <library> --output <work>/import-plan.json`.

Inspect every planned identity, source/target, hash, provenance, skipped item and collision. Then explicitly run `arp library apply --plan <actual-produced-plan.json>`. Keep plans, backups and journals.

Expected output: audit JSON/CSV/report, missing or ambiguous pair diagnostics, staged verified replacements or organization/import plans, and a reversible apply journal. Original BibTeX bytes, BOM, encoding and line endings survive.

Recovery: rerun an interrupted apply with the same plan; a completed apply is idempotent. `arp library apply --plan <actual-produced-plan.json> --rollback` restores backed-up state only when output/backup hashes remain valid. Re-audit and create a new plan after external edits instead of forcing the old plan. A concurrent apply lock is a wait/resume condition.

Limits: registry metadata does not prove official PDF bytes or final publication status. The manual ScienceDirect watcher accepts only stable new/changed local downloads and never controls a browser. See [library mode](../references/library-mode.md).
