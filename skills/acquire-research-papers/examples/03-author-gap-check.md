# Author gap check and acquisition

Input: copy [author.json](inputs/author.json), supply the actual name and available ORCID/DBLP/homepage evidence, exact date range and `local_dir`. Never guess an identity ID. Optional [empty-metadata.json](inputs/empty-metadata.json) is an explicit offline metadata map for library audit.

```text
arp discover author --spec <work>/author.json --output <work>/author-discovery
arp library audit <library> --metadata <work>/empty-metadata.json --output <work>/library-audit
```

The author command already compares exact DOI when `local_dir` is set. Inspect `author-discovery.json`, source coverage, identity uncertainty, missing-pair states, and issue/online date evidence. For additional inputs, normalize only reviewed records into separate JSON `records` arrays, then use `arp collection compare --left <work>/author-records.json --right <work>/local-records.json --output <work>/comparison.json --run <work>/comparison-run`. Title similarity is a hint, not a merge rule.

Review namesakes and distinct preprint/published identities. Fetch only reviewed missing identities with `arp fetch --input <DOI> --output <delivery>/<paper-key>`, or freeze identity-reviewed records and acquire a selection as described in [capabilities](../references/capabilities.md). Stage verified pairs with `arp library import <delivery> --destination <library> --output <work>/import-plan.json`; inspect the plan, then use `arp library apply --plan <work>/import-plan.json`.

Expected output: formal/early-access/preprint groups, explicit coverage and uncertainty, exact-identity local gaps, optional official deliveries, and a reviewed library plan.

Recovery: preserve completed discovery as a snapshot; rerun in a fresh output for changed time/identity scope. Acquire other papers while manual or rate-limited items remain pending. Apply resumes its journal and is idempotent; rollback uses the same plan with `--rollback` and rejects later output changes.

Limits: public author sources can be incomplete or truncated; never call the bibliography universally complete. This recipe is a composition, not a new author-gap kernel mode.
