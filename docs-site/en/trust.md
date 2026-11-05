# Trust and limitations

## Accuracy and trust boundaries

The project improves reliability in three different ways:

- **Coverage accountability:** venue/year enumeration and a coverage ledger are stronger than trusting the first page of keyword results. They still cannot guarantee that upstream indexes contain every paper.
- **Relevance accountability:** deterministic hard gates and prefiltering reduce noise, but an accepted paper requires a recorded agent judgment over title and abstract. This is more auditable than keyword-only acceptance, not a proof of universal semantic accuracy.
- **Artifact identity:** official-host boundaries, raw publisher BibTeX, metadata comparison, provenance, and hashes give the strongest guarantee in the system: the delivered files correspond to the frozen paper.

The repository has regression tests for its contracts and has completed real multi-venue corpus runs. It does not yet have a large, independently labeled cross-domain benchmark, so it must not advertise a measured precision/recall score. Missing abstracts, incomplete current-year indexes, ambiguous records, and boundary relevance judgments are reported rather than guessed.

## Current limitations

- The full IEEE/CARSI path has been live-validated with one CARSI institution. Every additional institution is profile-driven but still requires first-use observation and adaptation.
- Editable credential files and core commands are portable. Current IEEE browser integration and legacy DPAPI remain Windows-specific; Claude Code and Kiro interactive execution have not been live verified.
- IEEE journal discovery relies primarily on Crossref and optional metadata APIs; there is no official IEEE venue enumerator in the current release.
- ACM automation has no browser-backed production adapter. Official pages that block the HTTP client become manual items.
- ScienceDirect acquisition is manual only; the project intentionally does not automate organization login or the article page.
- Research mode is staged and requires explicit agent candidate and evidence decisions; it is not an unattended one-command systematic review.
- Citation-graph coverage is bounded by configured seeds, neighbor limits, provider coverage, and API availability; it cannot prove universal recall. The search-saturation record describes only the run's own queries and bounds.
- A paper without a trustworthy abstract remains `pending_abstract`; title-only acceptance is forbidden.
- New or not-yet-published proceedings and inconsistent upstream metadata can leave coverage incomplete.
- `arp config status: true` confirms stored configuration shape, not live credentials, quota, subscription, or API entitlement.
- Large authenticated batches run conservatively and may be slow.
- Existing-folder library operations require an explicit reviewed hash-bound plan; unknown PDF/citation identity remains a manual review item.
- The internal generic publisher adapter is not a public plug-in system yet.
- No cross-domain labeled benchmark currently supports a numeric precision/recall claim.

## Responsible use

Use institutional access only within the account and license terms that authorize the requested material. The project does not bypass publisher controls, redistribute acquired papers, automate prohibited publisher interactions, or weaken an institution's authentication flow.
