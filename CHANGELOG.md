# Changelog

## 0.15.0 — 2026-11-04

- Fixed on Windows: a batch acquisition with parallel hosts (the default since 0.10.0) could stop with "acquisition output contains an unverified reserved artifact" right after delivering a paper. When one host's worker created a shared venue folder while another worker was resolving a path inside it, Python's `Path.resolve()` returned the `\\?\C:\…` spelling of the path, so the delivered file no longer matched its reserved path. Paths are now compared without that prefix. Reproduced in isolation (282 of 300 trials returned the prefixed path) and in the test suite under CPU load; 0 of 20 loaded runs fail now.
- A server error (HTTP 5xx) from a publisher now says "the publisher's server failed, so rerun later". Since early November 2026 `ojs.aaai.org` has answered its citation exports (BibTeX, RIS, and ACM formats) with HTTP 520 for every client, while its article pages and PDFs work, so AAAI papers stay `network_transient` until AAAI fixes it. No other citation format is used in place of the official BibTeX.
- Maintainers: the `weekly source check` also fetches the release smoke's open-access papers (ACL, AAAI, NeurIPS, PMLR, CVF, IJCAI) through `arp fetch` and requires delivery (`--only fetches`). A check that fails with a connection error, HTTP 5xx, or HTTP 429 runs once more after 30 seconds and is marked as retried; a second such failure is reported as `upstream_error` and a workflow warning instead of failing the run. Error text keeps only the host of each URL, so an API key in a query string cannot reach the report.
- Maintainers: `python scripts/release.py smoke` retries a transient fetch once into a fresh folder ("after a retry") and fetches an IJCAI DOI too. `python scripts/release.py remote --host <user@host>` installs the built skill ZIP on a Linux or macOS host over SSH: it checks the ZIP hash on the host, backs up each installed skill to `~/.arp-skill-backups/`, installs into `~/.kiro/skills` and `~/.codex/skills`, and requires each to report the new version and runtime pin. `build` refuses to finish when either README does not link the new release tag, `CHANGELOG.md` lacks the new section, or the wheel's embedded README is stale.

## 0.14.0 — 2026-11-04

- IJCAI works again. In 2026 IJCAI moved to `ijcai.org` (with `www.ijcai.org` redirecting there) and redesigned its index and paper pages, so 0.13.0 failed every IJCAI discovery and fetch with a host-boundary or page-contract error. Both hosts are accepted now, and the new layout is read: detail links that appear twice per paper, the "PDF Download" label, the repeated BibTeX link, "Family, Given" authors, and the new abstract and keyword blocks; the old layout still parses. Live: IJCAI 2023 lists 639 main-track papers, sample pages parse with abstracts, and papers from 2023 and 2024 deliver from DOI, `www.ijcai.org`, and `ijcai.org` links.
- `arp review template --run <discovery-run> --output <file> --reviewer <host> --rule-version <id>` writes an importable decisions file with one `pending` record per ready evidence packet, already carrying its candidate ID, evidence hash, and v2 reviewer metadata, so a reviewer only fills in decisions and reasons. Live: a 256-paper INFOCOM 2024 template with three accepts froze the same selection as hand-written decisions.
- 20 more venue presets, each checked live: 18 IEEE journals (TCCN, TGCN, TMLCN, TII, TSP, TC, TDSC, TIFS, TEVC, TCYB, TNNLS, TSMC, T-IV, T-SUSC, TETC, Transactions on Big Data, T-ASE, TIT) and, through per-edition Crossref proceedings DOIs, ACM MobiCom 2022–2025 and MobiHoc 2021–2026. The ToN preset gains ISSN 2998-4157: IEEE/ACM Transactions on Networking became IEEE Transactions on Networking in 2025, and the old ISSN has no records from 2025 on, so 0.13.0 found no ToN 2025 papers. Live: ToN 2025 enumerates 257 records and MobiCom 2024 286.
- A venue with several ISSNs is enumerated in one Crossref request (Crossref ORs repeated filters), so each work arrives once; before, only the first ISSN was used.
- Maintainers: `python scripts/release.py smoke [--public]` runs the release smoke test from the repository (built ZIP and wheel, or the public release URL) with expected outcomes per check; `scripts/check_sources.py` and the `weekly source check` workflow recheck every preset and official index each Monday. Its first run found the IJCAI and ToN changes above.

## 0.13.0 — 2026-11-04

- `manual-fetch --queue --open-all` opens the official pages of the first 30 waiting papers at once, with a short pause between pages, so the user can work through the tabs in any order while the session imports each verified pair; later papers open in turn. `manual-download.html` shows this command. Browsers block a local page from opening many tabs with one click, so the page offers the command instead of a button.
- Maintainers: `scripts/release.py` runs the release steps (`bump`, `build`, `publish`). It rewrites every version string all or nothing, proves the build reproducible and writes `SHA256SUMS`, checks that the release commit, tag, and CI are in place, uploads each asset with retries, publishes the draft, and compares the downloaded assets with the local build. See CONTRIBUTING.md.
- The DPAPI credential test allows 180 s for Windows PowerShell to start; a CI runner once needed more than the previous 30 s.

## 0.12.0 — 2026-11-04

- A rerun of `discover corpus` into the same output now looks up missing abstracts again while candidates are pending, through every configured enricher, including one a newly added API key enables; finished venue slices are not fetched again. Before, a run whose slices were all complete did nothing on rerun, so adding a key meant discovering into a new directory. Live: after an OpenAlex key was added, rerunning a key-less IEEE TMC 2024 run filled one of its two remaining abstracts without enumerating the venue through Crossref again.
- A rerun also reads a slice with a `possible_upstream_lag` warning again: works indexed since are added and the warning goes once the count recovers. A recheck that fails keeps the complete slice and its warning for the next rerun. A run with nothing pending and no warning stays idempotent.

## 0.11.0 — 2026-11-04

- Built-in venue presets: a corpus spec can name a venue by its short name (`name: INFOCOM`, `name: IEEE TMC`) and receive an identifier checked live in November 2026: an ISSN for 19 IEEE journals (TMC, TWC, JSAC, IoT-J, TVT, TCOM, ToN, TNSE, COMST, Wireless Communications, Network, TPDS, TCC, TSC, T-ITS, TNSM, WCL, COMML, TAES) and AAAI, and an OpenAlex series for INFOCOM, ICC, GLOBECOM, WCNC, VTC, ICDCS, ICNP, IWQoS, SECON, and SIGCOMM. A preset applies only when the venue declares no identifier of its own and no different publisher; `preset: <id>` selects one explicitly and `preset: none` turns matching off. The applied preset is recorded in `request-spec.json`, and `arp sources` lists the presets with their evidence and shows the preset of each slice.
- OpenAlex lag warning: when a finished `openalex-venue` slice holds under half the works of the previous year (and that year has at least 50), discovery adds a non-retryable `possible_upstream_lag` diagnostic, counts it as `coverage_warnings` in the output and manifest, and lists a `check_coverage` next action. The slice stays `complete`. Live: INFOCOM 2025 (25 works against 262 in 2024) is flagged.
- When abstracts stay pending and a Semantic Scholar or OpenAlex key is missing, `discover corpus` lists `next_actions` with the `arp config setup` command for each missing key; `arp doctor` notes the missing keys.

## 0.10.0 — 2026-11-04

- IEEE conferences can be enumerated through OpenAlex: a venue that lists exact `openalex_source` IDs is read by the new `openalex-venue` enumerator (every work of that source and year, with DOIs and abstracts), and Crossref no longer reports it as `exact_identifier_required`. `arp sources --find-openalex "<name>"` looks up source IDs, and `arp sources --spec` shows the route per slice. Live: INFOCOM 2024 (262 papers) and ICC 2024 (940) enumerated completely, 1,191 of 1,202 with abstracts, all routed to IEEE Xplore. An OpenAlex API key is required.

- Batch acquisition contacts up to four publisher hosts at the same time (`--parallel-hosts N` on `acquire corpus`, `acquire research`, and `acquire selection`; `1` restores one paper at a time). Each host still gets one paper at a time with the same spacing and pauses, one adapter never serves two papers at once, and the ledger keeps selection order. A live nine-paper batch across six publishers took 67 s instead of 166 s.
- Acquisition writes `manual-download.html` beside `manual-download.csv`: a static, escaped checklist of every manual item with its official link, target filenames, and the `manual-fetch --queue` command. It is removed when the queue empties.
- `arp job list` lists the background jobs started on this machine, newest first, with their status. `job status` retries briefly when `job.json` is momentarily unreadable.
- A publisher answer of HTTP 401/403 now says to download the paper in a browser and import it with `manual-fetch`; a Cloudflare bot check (as ACM Digital Library returns for every non-browser request) is named as such.

## 0.9.0 — 2026-11-04

- A Springer Link adapter acquires journal articles and book chapters such as LNCS papers, from a `10.1007` DOI or a `link.springer.com` URL: the official PDF and the BibTeX file from Springer's citation export service, which the page links. It delivers when the page states that this network has access (open access everywhere, subscription papers on an entitled network) and otherwise reports `access_required`; it never logs in. A chapter export's DOI is read from its entry key, which Springer uses instead of a `doi` field.
- A rerun of `acquire corpus`, `acquire research`, or `acquire selection` no longer requests a paper whose last attempt was refused (`access_required` for the paper itself, recorded as `access_refused` in the ledger) and reports such papers as `not_retried`. This stops repeated institution logins and repeated refusals. `--retry-manual` requests them again. Deferred papers, papers of a paused host, papers whose institution login failed, and `unsupported_adapter` papers are still requested.
- Corpus discovery skips the optional OpenAlex and Semantic Scholar topic searches when official indexes complete every requested venue/year slice, since those searches could then only add papers from other venues.
- `arp --background <job-dir> <command>` runs a long `fetch`, `manual-fetch`, `discover`, or `acquire` command in its own process and returns at once, so a host's command timeout cannot cut it off. `arp job status --job <job-dir> [--wait N]` reports progress and the command's final JSON, and `arp job stop` ends it as Ctrl+C would (`--force` kills it).
- `manual-fetch --queue` works through the whole manual-download queue of a finished corpus or research acquisition in one session. With `--watch` it opens each queued paper's official page in turn and imports pairs in whatever order the user downloads them; a paper whose pair does not arrive within `--timeout` is skipped, and its files still count if they arrive later in the session. With `--from <folder>` it imports pairs that are already downloaded, without waiting. Every file is checked against every waiting paper; a file that identifies more than one paper is never assigned, and distinct valid duplicates leave the paper `ambiguous`. The session then updates the acquisition ledger, `manual-download.csv`, and the paper and delivery manifests without contacting a publisher. Ctrl+C ends it with the same update.
- Outside Windows, IEEE papers are `unsupported_adapter` items in the manual-download queue instead of `configuration_required` errors, and `arp doctor` reports `ieee_browser: unsupported_platform` with an explanatory `notes` entry instead of asking to install Windows and Chrome. The overall doctor status is no longer `attention_required` for this platform limit alone.
- Older IEEE DOIs that doi.org still sends to plain-HTTP `ieeexplore.ieee.org` addresses (for example `10.1109/CVPR.2016.90`) are upgraded to HTTPS without a request instead of failing as `contract_error`.

## 0.8.0 — 2026-11-04

- Corpus discovery enumerates three more official archives: the NeurIPS yearly listing (main track and, from 2022, Datasets and Benchmarks), PMLR volumes of ICML, AISTATS, COLT, UAI, CoRL, ALT, ACML, L4DC, and CLeaR (one official BibTeX file per volume, abstracts included), and CVF Open Access listings of CVPR, ICCV, and WACV, including pre-2021 per-day pages. Candidates carry the landing URL the acquisition adapters accept, so these venues now run end to end in batch mode, and Crossref skips any slice these indexes complete.
- NeurIPS and CVF read paper pages with bounded concurrency; a resumed partial slice rereads only papers still missing. A paper failure costs that paper, not the slice. A CVPR or ICCV venue declared with `publisher: IEEE` keeps the IEEE route.
- `arp sources` lists the new indexes and their artifact type. AAAI remains a Crossref venue (by ISSN) whose records already carry abstracts and OJS landing URLs.

## 0.7.0 — 2026-11-03

- Added automatic acquisition from four official open-access archives: AAAI OJS (PDF and OJS BibTeX export; AAAI DOIs work), NeurIPS proceedings (PDF and per-paper BibTeX file), PMLR, and CVF Open Access. PMLR and CVF publish no BibTeX file; their delivered BibTeX is the entry printed on the official page, recorded as `publisher_page_embedded`. CVF deliveries are CVF's open-access versions, not the final IEEE Xplore versions. Legacy `papers.nips.cc` and `/paper/<year>/` NeurIPS links and plain-HTTP links to these archives are canonicalized without a request. None of the four archives has an official venue enumerator yet; NeurIPS, PMLR, and CVF acquisition needs the landing-page URL.
- Corpus and research acquisition checkpoint the ledger after every paper. An interrupted run resumes with the same command: verified pairs are adopted, the interrupted paper's leftovers move to `.arp-interrupted/`, any other blocking file is named, and `run status` reports `interrupted`.
- One failure classification serves every acquisition path. Publishers without an adapter enter the manual queue as `unsupported_adapter`; publisher 5xx, DOI resolver network failures, and IEEE navigation failures are retryable; unexpected browser failures are `automation_error` and report only the exception class. `fetch` reports publisher HTTP errors without a traceback.
- DOI resolution retries with backoff, follows DOI alias hops, and maps Elsevier link-resolver targets to the manual ScienceDirect route. `--defer-host` matches DOI-only records of supported publishers. Publisher HTTP clients back off 1, 2, then 4 seconds.
- IEEE papers of one run share one dedicated browser (`ARP_IEEE_REUSE_BROWSER=0` opts out); page steps are bounded at 120 s separately from the user's login wait; a transient citation export is retried before the downloaded PDF is discarded. The pinned Playwright installer now accepts the runtime data root.
- Batches space requests per publisher host and pause a host for the rest of the run after HTTP 429, three consecutive transient failures (`host_paused`), or an institution login failure. `doctor` reports IEEE browser prerequisites.
- Tests are isolated from real configuration: `AppPaths.for_root()` no longer lets `ARP_CONFIG_ROOT` override its explicit root.
- `SKILL.md` routes every mode, adds one result-to-next-action table, and is the single copy of the access boundaries; examples use the portable `arp` shorthand.

## 0.6.0 — 2026-10-21

- New research runs write only discovery state until evidence review, then one `reports/report.md` with located evidence, claim coverage, pending work, scope and an applicable bounded gap conclusion. `evidence research --export-csv` adds merged `papers.csv` and `claim-coverage.csv`; runs without `output_version` keep their legacy layout on resume.
- Author discovery and library audit default to JSON plus a brief report; `--export-csv` enables spreadsheet views. Resolved metadata/research/download queues disappear and absent paths return JSON null. Hash-bound corpus review queues and acquisition `paper-manifest.csv` remain for compatibility.
- Added offline `arp sources` and `arp sources --spec <corpus.yaml>` inventory/venue-year diagnostics. Official ACL/IJCAI indexes, metadata enumeration, artifact acquisition and observed coverage are distinguished. Priority venues remain unselected; no claim of complete conference/journal coverage or new live certification is made.
- Reduced the main skill to three common routes with advanced references; combined Related Work and gap analysis into a shared recipe and reorganized bilingual output guidance by workflow and phase. Official raw BibTeX, identity checks, frozen hashes, recovery, backup/rollback and access boundaries are preserved.

## 0.5.0 — 2026-10-20

- Added independent capability commands for identity, discovery, enrichment, collections, reviews, immutable selection, acquisition, local verification, PDF parsing, evidence validation and export, with lightweight hash-checked run status and recovery. Existing corpus/research/author entrypoints and frozen identities remain compatible.
- New installations use editable local dotenv credentials, explicit file selection, no interpolation, private permissions, isolated institution files, and non-secret status. Existing DPAPI stores remain selected until explicit conflict-safe migration on the original Windows account.
- Shared v2 review provenance records the actual host and available model metadata while preserving legacy Codex review bytes/hashes. Added host-aware safe copy targets, read-only local `doctor --host`, Codex/Claude Code/Kiro installation guidance and a Kiro `skill://` resource template. Documentation compatibility is separate from live host validation.
- Added seven composition recipes with input templates, expected outputs, recovery and limits. Official PDF/raw BibTeX pairing, exact credential hosts, institution/browser isolation, manual ScienceDirect interaction and library backups/rollback remain in force.

## 0.4.0 — 2026-10-20

This is the first packaged GitHub release. It includes the previously developed acquisition, corpus, and research commands alongside the following additions.

### Institution access

- Named IEEE institution profiles isolate configuration, DPAPI credentials, and browser sessions. `direct`, `assisted`, and explicit-contract `carsi` access are separate choices; first setup defaults to assisted manual login.
- Added `config setup`, IEEE `list/use/login/doctor`, non-secret form inspection, typed locators, and legacy single-institution migration. Existing PowerShell entrypoints remain available.
- Manual login retains its visible browser until completion, cancellation, or timeout. MFA and unfamiliar pages require user action; transport retries do not resubmit credentials.
- Diagnostics distinguish configuration, authentication, IEEE return, verified artifacts, and institutional entitlement. Historical timestamps are explicit; failed live checks replace older success records. Open-access downloads do not prove subscription access.

### Local libraries and authors

- Added `library audit/update/import/organize/apply`, staged hash-bound changes, backup/journal recovery, idempotent apply, rollback, and concurrent-apply protection.
- PDF version evidence, citation placement, first-online dates, and formal issue dates are recorded separately. Unverified identities and multi-DOI ambiguities require review.
- Original BibTeX bytes, BOM, encoding, line endings, and hash-bound publisher provenance are preserved. IEEE export strings remain verbatim.
- Added title-based paired filenames, explicit chapter identity/page maps with retained source books, and a bounded manual ScienceDirect queue/watch/import workflow.
- Added public author discovery across ORCID, DBLP, supplied homepages, and Crossref. Formal publications, Early Access, and preprints remain separate; issue dates are primary, identities may be ambiguous, and source coverage is never claimed complete.

### Installation

- The sole source skill is `skills/acquire-research-papers/`. Standard `npx skills add` installs this small subtree.
- The portable launcher verifies a fixed release wheel and installs it with uv outside the skill. The wheel carries runtime browser/PowerShell helpers and schemas; user skill packages exclude source checkouts and development dependencies.
- Added exported skill folders, a downloadable ZIP, runtime schema output, and a safe copy installer that refuses Git checkouts.
- Added bilingual installation/migration guidance, troubleshooting, structured issue templates, release checksums, and public-install verification.

### Validation and limits

Python, Node, and PowerShell regressions use synthetic/redacted fixtures and temporary stores. Public-install smoke tests exercise the real release download without a local-wheel override. Windows remains required for IEEE browser/DPAPI workflows; public metadata and local-library operations remain portable. This release does not establish live validation for every institution, universal author completeness, or measured cross-domain search precision/recall. ScienceDirect page/login automation remains outside the supported workflow.

Earlier development history is available in the [commit log](https://github.com/EnosElinsa/acquire-research-papers/commits/main/); no earlier packaged GitHub releases were published.
