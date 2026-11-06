# Corpus mode

Use this reference for venue/topic/year/count collection tasks, including task files and role-scoped assignments.

## Normalize the request

Create a `CorpusSpec` conforming to `schemas/corpus-spec.schema.json`. Capture:

- minimum, preferred, and maximum totals;
- exact venue names, aliases, type, optional venue-specific years, optional ISSN/ISBN, and optional Crossref collection DOI values;
- included and prioritized years;
- included and excluded publication types or tracks;
- positive topics, synonyms, and exclusion concepts;
- group, venue, year, publication-type, and recent-window quotas;
- output profile, numbering, PDF/BibTeX requirements, and explicit Markdown choice.

Natural language is the usual input. A DOCX, Markdown, TXT, CSV, DOI list, or URL list is only an adapter. If the file contains several people or sections, use a `scope_selector` derived from the user's instruction and preserve the extracted constraints in the run provenance.

## Enumerate, enrich, and prepare evidence

Enumerate every requested venue/year slice before topic screening. Official indexes and venue enumerators run only for venues the spec names; a spec without venues gets only the keyword-search candidates of a configured OpenAlex or Semantic Scholar key, and a few papers on a topic across many venues are better found with `discover candidates` ([topic surveys](../examples/08-topic-surveys.md)). Use an official proceedings index where supported and a paginated Crossref venue/date stream as the generic source. Official indexes exist for ACL, IJCAI, NeurIPS, ICLR (from 2024; earlier years are OpenReview-only and `source_unavailable`), the PMLR conferences (ICML, AISTATS, COLT, UAI, CoRL, ALT, ACML, L4DC, CLeaR), CVF (CVPR, ICCV, WACV), and USENIX (USENIX Security, OSDI, NSDI, USENIX ATC, FAST); `arp sources --spec` shows which one a venue uses. The USENIX index reads one technical-sessions page per edition, 10 s apart. Their candidates carry the archive landing URL that acquisition needs, and Crossref skips a slice an official index completed. NeurIPS and CVF read one page per paper, so a large year takes several minutes; a resumed partial slice rereads only the papers still missing. A CVPR or ICCV venue declared with `publisher: IEEE` skips the CVF index and keeps the IEEE route. AAAI has no archive index; enumerate it through Crossref with its ISSN. ISSN identifies journals. Without an ISSN, Crossref enumeration uses the exact `container-title` filter. For a Crossref-indexed proceedings collection, set `collection_doi` to the parent DOI values; the provider enumerates records through Crossref's exact `alternative-id` filter. A conference declared with `kind: conference` and no official provider or collection DOI is reported as incomplete instead of treating fuzzy title search as exhaustive. IEEE conferences usually have no such identifier in Crossref, so enumerate them through OpenAlex: find the series' source ID with `arp sources --find-openalex "<series name>"` (for example `S7407087743` is "IEEE Conference on Computer Communications (INFOCOM)"; take the series itself, not its workshops) and list it in the venue's `openalex_source`. The `openalex-venue` enumerator then reads every work of that source and publication year, with DOIs and abstracts, under the spec's venue name, and Crossref leaves that venue alone; it needs an OpenAlex API key. OpenAlex can lag behind a recent edition: when a finished slice holds under half the works of the previous year (and that year has at least 50), discovery adds a non-retryable `possible_upstream_lag` diagnostic and a `check_coverage` next action, counts it in the manifest's `coverage_warnings`, and keeps the slice `complete`. Compare `records_recognized` in `coverage.jsonl` with the edition's proceedings before relying on such a slice. Every rerun of the same command into the same output reads a warned slice again: works indexed since are added, the warning goes once the count recovers, and a recheck that fails keeps the complete slice and its warning for the next rerun.

Built-in venue presets supply checked identifiers so a spec can name a venue by its short name. A venue whose `name`, `short_name`, or an alias matches exactly one preset (case and punctuation ignored), that declares no `issn`, `isbn`, `collection_doi`, or `openalex_source` of its own, and whose declared `publisher` (if any) is the preset's, receives the preset's ISSN or OpenAlex source plus its kind, publisher, short name, and full name as an alias. `preset: <id>` selects a preset for any name and `preset: none` turns matching off; a preset written next to different identifiers is a spec error. The applied preset ID is recorded in `request-spec.json`, and `arp sources` lists every preset with the evidence it was checked against (Crossref title and 2024 count for an ISSN, OpenAlex count with publication year matching the edition for a series). Journal presets (47 IEEE journals and Wiley's Journal of Field Robotics): TMC, TWC, JSAC, IoT-J, TVT, TCOM, ToN, TNSE, COMST, Wireless Communications, Network, TPDS, TCC, TSC, T-ITS, TNSM, WCL, COMML (Communications Letters), TAES, TCCN, TGCN, TMLCN, TII, TSP, TC, TDSC, TIFS, TEVC, TCYB, TNNLS, TSMC, T-IV, T-SUSC, TETC, Transactions on Big Data, T-ASE, TIT, and the robotics, automation, and control journals T-RO, RA-L, T-Mech, TIE, TIM, JAS, RAM (Robotics & Automation Magazine), TCST, TCDS, and T-FR, which list both their print and electronic ISSNs. T-FR (IEEE Transactions on Field Robotics) continues the journal Field Robotics and carries both journals' ISSNs. JFR (Journal of Field Robotics) is discovery only: Wiley Online Library answers non-browser requests with a Cloudflare challenge, so its papers are manual downloads. ToN carries both ISSNs: IEEE/ACM Transactions on Networking became IEEE Transactions on Networking in 2025 and its old ISSN has no records from then on; a venue with several ISSNs is enumerated in one Crossref request, so each work arrives once. Conference presets: AAAI (ISSN); through OpenAlex the IEEE series INFOCOM, ICC, GLOBECOM, WCNC, VTC, ICDCS, ICNP, IWQoS, and SECON plus ACM SIGCOMM; and through Crossref proceedings DOIs ACM MobiCom 2022–2025 and MobiHoc 2021–2026, one DOI per edition (an edition not listed needs its own `collection_doi`). ACM papers stay manual downloads. `scripts/check_sources.py` rechecks every preset weekly.

Abstracts come from the enumerator or from DOI enrichment through Semantic Scholar (keyless at a shared, low rate limit) and OpenAlex (key required). When candidates stay in `pending-metadata.csv` and a key is missing, `discover corpus` lists `config setup` next actions with the exact command (`arp config setup semantic_scholar` or `arp config setup openalex`); `arp doctor` notes the missing keys too. While candidates lack an abstract, every rerun of the same command into the same output keeps the finished venue slices and looks up the missing abstracts again through every configured enricher, so after adding a key just rerun. A run with nothing pending and no coverage warning stays idempotent: its rerun contacts no source. OpenAlex and Semantic Scholar may enrich or expand candidates, but they do not establish final citation artifacts. Preserve the source, record ID, observed fields, recognized/emitted record counts, coverage state, and sanitized request provenance.

Apply hard gates before semantic relevance:

1. venue or proceedings identity;
2. year/date range;
3. publication type and track;
4. DOI/version identity;
5. explicit topic exclusions.

The deterministic lexical prefilter is high recall and produces review signals only. It never rejects a hard-gate-passing candidate for lacking an exact phrase. Normalize case, Unicode separators, hyphens, plurals, and common inflections. A candidate without an abstract goes to `pending-metadata.csv`; keywords are optional.

Discovery and selection are separate phases. Discovery prepares immutable evidence. The executing agent then decides semantic relevance from title and abstract; keywords are optional and full text is not required. Selection is frozen only after those decisions pass hash and schema validation.

Run discovery as its own phase (`arp` means `python <skill-directory>/scripts/arp.py`):

```text
arp discover corpus --progress --spec <job.yaml> --output <discovery-run>
```

`--progress` writes sanitized JSON lines to stderr with closed phase names, provider slugs, and integer counts. The final result remains the only JSON object on stdout. DOI abstract enrichment runs Semantic Scholar first and, when its independent key is configured, OpenAlex second; a Semantic Scholar rate limit does not prevent the OpenAlex pass. The optional OpenAlex and Semantic Scholar topic searches run only while some requested venue/year slice lacks a complete official index; once official indexes complete every slice they would only return other venues' papers, so they are skipped (progress event `provider_skipped`).

Discovery produces:

- `request-spec.json`: the normalized request used by this run;
- `coverage.jsonl`: complete, partial, or failed state for each provider venue/year slice;
- `candidates.jsonl`: every merged candidate, hard-gate result, metadata state, and prefilter signals;
- `evidence-packets.jsonl`: immutable review evidence with candidate ID and SHA-256;
- `pending-metadata.csv`: candidates that still lack title or abstract evidence;
- `discovery-errors.jsonl`: sanitized provider and page diagnostics;
- `discovery-manifest.json`: request hash, candidate/evidence/coverage hashes, counts, provider coverage, and artifact names.

It does not write `selected-papers.jsonl`, resolve publisher artifacts, or write PDF, BibTeX, acquisition, manual, or retry files. Retry the same output directory when coverage is partial; completed slices are checkpointed and candidates are merged by stable identity.

## Review and freeze

Start the decisions file from a template that already carries every ready packet's `candidate_id`, `evidence_hash`, and the v2 reviewer metadata, all `pending`:

```text
arp review template --run <discovery-run> --output <review-decisions.jsonl> --reviewer <actual-host> --rule-version <id>
```

Then change only `decision`, `reason`, and (for an accept) `matched_topics` of the papers you judge; the file imports as it is, and untouched papers stay pending. Packets still missing an abstract are left out, since they cannot be accepted. Add `--model` only when the model is actually known.

Read `evidence-packets.jsonl` and write `review-decisions.jsonl`. Each record must contain:

- `candidate_id` and the unchanged `evidence_hash`;
- `decision`: `accept`, `reject`, or `pending`;
- `matched_topics` and `evidence_fields` used by the decision;
- a concrete `reason`;
- `schema_version: 2`, `reviewer: <actual-host>`, matching `executor.host`, and a stable `rule_version`; include model/version only when known. Legacy Codex v1 reviews remain readable unchanged.

Use title and abstract for the decision; keywords are optional. Do not require publisher login or full text. Missing abstracts remain pending. Then import decisions:

```text
arp review corpus --run <discovery-run> --decisions <review-decisions.jsonl>
```

The importer verifies the request and all discovery artifact hashes, then rejects unknown/duplicate IDs, changed hashes, invalid enums, unsupported evidence fields, and acceptance without ready title-and-abstract metadata. It applies venue, year, publication-type, group, and recent-window quotas to accepted candidates and stops at the preferred total. A scalable early stop is valid only when the accepted pool already satisfies that preferred total and every quota. The manifest records `review_completion: target_satisfied_early_stop` and `ready_unreviewed`; every omitted ready packet remains in `pending-review.csv` and is excluded from selection. Otherwise, all ready packets require an explicit decision before the review can be complete. The workflow writes `reviewed-candidates.jsonl`, `pending-review.csv`, `selected-papers.jsonl`, and `selection-manifest.json`. Named shortfall classes distinguish coverage, evidence, review, and quota work. Never lower semantic criteria to fill a quota.

## Acquire and deliver

Acquire the frozen selection explicitly:

```text
arp acquire corpus --selection <discovery-run>/selection-manifest.json --output <delivery-root> --defer-host <publisher.example>
```

The acquisition phase verifies the selected-list hash and atomically writes `selection-binding.json` before any publisher request. It routes every frozen record through the same publisher adapters used by `fetch`; it cannot discover extra papers or change semantic decisions. An existing final manifest with the same hash can migrate to the binding contract. A corrupt ledger, a different selection hash, or an unbound/unverified reserved artifact stops the run before overwrite. Delivery is complete only when both files pass:

- official PDF validation and SHA-256 recording;
- official raw BibTeX parse and metadata comparison.

Reserved numbering and relative paths are assigned when selection is frozen, so automatic and manual acquisition target the same slots. A rerun skips a delivered item only when all three recorded paths and PDF, BibTeX, and provenance hashes still match.

The ledger is checkpointed after every paper. An interrupted run (Ctrl+C, host timeout, crashed browser) leaves `delivery-manifest.json` at status `in_progress` and the current paper as an `in_progress` row; `arp run status` reports it as `interrupted`. Rerun the same command and output: complete pairs whose provenance binds the selection ID and hashes are adopted, and leftovers of the interrupted paper move to `.arp-interrupted/<selection-id>/` instead of being deleted. Any other unverified file in a reserved path stops the run with its path named.

`--defer-host` is a repeatable, run-scoped control for temporarily disabling publisher contact without changing the selection. It accepts exact hostnames only and compares them case-insensitively; a DOI-only record of a supported publisher matches through its DOI registrant prefix. A matching item with no verified prior delivery becomes `manual_required` with `access_required`; a verified prior delivery is still reused. This is publisher-neutral and must not be implemented as a venue-specific selection filter. Host spacing and automatic host pauses are described in [acquisition workflows](workflows.md#ieee-xplore).

Papers of different publisher hosts are acquired at the same time, up to four hosts (`--parallel-hosts N`; `1` acquires one paper at a time). Each host still gets one paper at a time in selection order, with the same spacing and pause rules, and one adapter (for example the single IEEE browser) never serves two papers at once. A waiting institution login therefore holds only its own host. The ledger keeps selection order. Ctrl+C or `job stop` takes effect once the papers being downloaded finish.

Acquisition writes one durable state per selected paper to `acquisition-manifest.jsonl`:

- `delivered`: the official PDF and raw publisher BibTeX are verified;
- `manual_required`: authorized user interaction (`access_required`) or a publisher without an adapter (`unsupported_adapter`);
- `retryable`: a transient network, rate-limit, or browser failure, or a host paused for this run (`host_paused`);
- `contract_error`: the official page or returned artifact violates its contract, or a local prerequisite is missing (`configuration_required`).

It also writes `manual-download.csv`, `manual-download.html` (a static checklist of the same items with their official links, target filenames, and the `manual-fetch --queue` commands to import them, including the `--open-all` form), `retryable-downloads.csv`, and `delivery-manifest.json`. No outcome removes a record from `selected-papers.jsonl`. The delivered count, not the discovered count, determines acquisition completion.

A rerun requests every undelivered paper again except one whose last attempt was refused: the publisher or institution answered `access_required` for that paper itself (an entitlement gap, HTTP 401/403, a manual-only publisher, or a Springer page without access). Such a row carries `access_refused: true`, is kept as it is, and is counted in `not_retried`; this avoids reopening an institution login or repeating a refusal on every rerun. Deferred papers, papers of a paused host, and papers whose institution login failed are not refusals and are requested again. Add `--retry-manual` to request refused papers again after access has changed. `unsupported_adapter` papers are always requested again, so a newly added adapter picks them up.

## Review output

`candidates.jsonl` is an auditable candidate ledger, not a citation library. `pending-metadata.csv` contains discovery evidence gaps. `pending-review.csv` contains unresolved semantic decisions after import; acquisition failures never enter it. `manual-download.csv` contains only frozen selections that the user can retrieve from the official page after automated acquisition finishes.

Import the whole manual queue in one session after acquisition finishes:

```text
arp manual-fetch --selection <discovery-run>/selection-manifest.json --queue --output <delivery-root> --watch <download-directory>
arp manual-fetch --selection <discovery-run>/selection-manifest.json --queue --output <delivery-root> --open-all
arp manual-fetch --selection <discovery-run>/selection-manifest.json --queue --output <delivery-root> --from <folder-with-downloads>
```

With `--watch` (default: the user's Downloads folder), the session opens each queued paper's official page in turn and prints which paper to download. Add `--open-all` to open the official pages of the first 30 waiting papers at once (with a short pause between pages) so the user can work through the browser tabs in any order; later papers open in turn, and a page that did not open is tried again at its turn. `--open-all` cannot be combined with `--from` or `--no-open`. Browsers block a local page from opening many tabs with one click, so `manual-download.html` shows this command rather than a button. Files that exist before the session starts are ignored. The user may download in any order: every new stable file is checked against every waiting paper, and a paper is imported once exactly one verified PDF and one verified raw BibTeX identify it. After `--timeout` seconds (default 900) without a pair, the session moves to the next paper; files for a skipped paper that arrive later in the session still count. Ctrl+C ends the session. With `--from`, the session imports pairs already in that folder and does not wait or open pages. A file that identifies more than one queued paper is never assigned, and two distinct valid files for one paper leave it `ambiguous`; import such a paper with `--key`. The session then updates `acquisition-manifest.jsonl`, `manual-download.csv`, `paper-manifest.csv`, and `delivery-manifest.json` without contacting any publisher, and reports per paper `imported`, `already_imported`, `waiting`, or `ambiguous` with the reason. The command can take as long as the user needs; run it where it is not cut off by a short command timeout. Rerunning it continues with the papers still waiting.

Import one manual pair with the immutable selection identity:

```text
arp manual-fetch --selection <discovery-run>/selection-manifest.json --key <selection-id> --output <delivery-root> --watch <download-directory>
```

Both modes trust neither editable CSV values nor filenames. They verify the frozen list, official identity, PDF, and raw publisher BibTeX before filling the reserved paths. Do not add a source-specific shortcut.

## Output lifecycle

`pending-metadata.csv`, acquisition `manual-download.csv` and `manual-download.html`, and `retryable-downloads.csv` exist only when nonempty; absent paths are null. Resolving their items removes the known generated queue on rerun. Corpus review `pending-review.csv` remains part of the hash-bound review contract, including its empty completed form. Keep request, candidates, evidence packets, coverage, discovery errors, review/selection manifests and acquisition ledgers for recovery. `paper-manifest.csv` remains the delivered inventory. Use `arp sources --spec <corpus.yaml>` before discovery to inspect offline source capability; actual coverage comes from `coverage.jsonl`.
