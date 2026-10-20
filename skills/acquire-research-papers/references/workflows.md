# Acquire Research Papers

Deliver a verified pair for every paper: the official publisher PDF and the publisher's raw BibTeX export. Discovery services may nominate candidates; they never supply the final citation artifact.

## Route the request

- Use `fetch` for a DOI, official URL, exact title, or explicit paper list.
- Use `manual-fetch` when an authorized publisher download must be completed by the user in a normal browser, especially subscribed ScienceDirect content.
- Use `discover corpus` for venue/topic/year/count tasks. It enumerates venue/year slices and creates auditable evidence packets; it does not freeze a selection or download publisher artifacts.
- Use `review corpus` after Codex has reviewed the evidence packets. It validates structured semantic decisions and freezes the quota-aware selection.
- Use `acquire corpus` to consume a frozen selection, verify supported publisher pairs, and separate manual and retryable items.
- Use `discover research` for gap analysis, nearest work, claim citations, citation expansion, or Related Work research.

An attached DOCX, Markdown, TXT, CSV, or role assignment is only an input adapter. Translate its relevant part into a generic corpus spec or research brief; never hardcode the document format or role.

## Invoke the CLI

```powershell
$skill = Join-Path $env:USERPROFILE ".agents/skills/acquire-research-papers"
python "$skill/scripts/arp.py" --help
```

Runtime state belongs under `%LOCALAPPDATA%\Codex`; delivery directories must be outside this public repository.

Read [configuration](configuration.md) for named profiles and provider setup. All setup/read helper scripts mentioned in older technical details are bundled inside the runtime wheel; invoke `arp config setup` from the installed skill.

### Automatic fetch

```powershell
python "$skill/scripts/arp.py" fetch --input <DOI-or-official-URL> --output <directory>
```

Use output only when the JSON status is `delivered`. A title that is not uniquely resolved must go through discovery.

For subscribed IEEE content, use only the named institution profile configured by the current user through `arp config setup ieee`. Assisted access leaves authentication to the user. A CARSI automatic profile includes the exact CARSI option and IdP entity ID, identity-provider host, form contract, and may include an official IEEE WAYF URL supplied by the institution. The repository provides no institution name, identity-provider host, form label, credential default, or WAYF default.
If the profile is absent or the page contract does not match it, classify the paper as `access_required`, add it to the corpus manual-download list, and continue; never guess an institution or selector.

After the unauthenticated PDF attempt fails, enter the profile's exact `ResourceAccessUrl` before institution selection. Write and verify the configured CARSI IdP entity ID before submitting discovery. If the profile contains an institution-supplied `IeeeWayfUrl`, use that exact IEEE-hosted route after the initial institutional login; otherwise revisit only the same `ResourceAccessUrl`. Never click a portal card. Allow at most three total gateway visits for the CARSI fallback path. If a configured institutional continuation page appears, require exactly one accept/continue control and allow at most one reject control; process at most three consecutive same-host continuation stages because some IdPs separate terms acceptance from attribute release. Never click reject. If a stage exposes one consent checkbox, select it only through its unique associated label and verify its checked state. The configured accept/continue control is automatic by default; use `--no-accept-ieee-attribute-release` to keep the headful page visible for manual action instead. After either path, report `access_required` if the page remains incomplete. A PDF request is forbidden until the same browser context has returned to the exact `ieeexplore.ieee.org` host.

When IEEE access fails for a previously untested institution, retain the visible browser and use the returned error payload to report only the sanitized stage and hostname. Adapt the institution profile first: correct its exact CARSI option, entity ID, IdP hostname, accessible form labels, resource gateway, and continuation controls, then retry one representative paper. Do not add a school-name branch or selector to the generic script. Change `ieee-playwright.mjs` only when observation proves a new generic page shape that cannot be expressed by the profile; add a regression test for that page shape before the implementation change. Preserve the exact-host credential boundary, one credential submission, shared persistent context, three-visit gateway limit, reject-button prohibition, visible manual continuation, and query-value redaction throughout adaptation.

### ScienceDirect manual handoff

Configure the DPAPI-protected Elsevier API key once in an interactive terminal:

```powershell
python "$skill/scripts/arp.py" config setup elsevier
```

Then start the watcher before the user downloads the official PDF and raw BibTeX:

```powershell
python "$skill/scripts/arp.py" manual-fetch --input <DOI-or-ScienceDirect-URL> `
  --watch $HOME\Downloads --output <directory>
```

The command opens only the canonical article page. The user completes organization login and clicks both downloads; the CLI takes over stable new files, verifies identity, copies the pair, and records `manual_publisher_download` provenance. If both files already exist, pass `--pdf` and `--bibtex` instead. This flow never invokes MinerU.

### Corpus discovery, corpus acquisition, and research

```powershell
python "$skill/scripts/arp.py" discover corpus --progress `
  --spec <job.yaml> --output <discovery-run>
python "$skill/scripts/arp.py" review corpus `
  --run <discovery-run> --decisions <review-decisions.jsonl>
python "$skill/scripts/arp.py" acquire corpus `
  --selection <discovery-run\selection-manifest.json> --output <delivery-root> `
  --defer-host <publisher.example>
python "$skill/scripts/arp.py" discover research --brief <brief.yaml> --output <directory>
python "$skill/scripts/arp.py" review research `
  --run <directory> --decisions <research-review.jsonl>
python "$skill/scripts/arp.py" acquire research --run <directory> `
  --defer-host <publisher.example>
python "$skill/scripts/arp.py" evidence research `
  --run <directory> --records <evidence-review.jsonl>
```

Discovery writes `request-spec.json`, `coverage.jsonl`, `candidates.jsonl`, `evidence-packets.jsonl`, `pending-metadata.csv`, `discovery-errors.jsonl`, and `discovery-manifest.json`. It writes no selection, PDF, BibTeX, acquisition ledger, or manual-download queue. Resume the same run to retry partial coverage; complete venue/year slices are checkpointed.

Codex must inspect `evidence-packets.jsonl` and create hash-bound JSONL decisions for review-ready candidates. Judge relevance from both title and abstract; keywords are optional supporting evidence. Full text is not required for corpus discovery. A missing abstract remains `pending` until metadata enrichment succeeds. Each decision records `candidate_id`, `evidence_hash`, `decision`, `matched_topics`, `evidence_fields`, `reason`, `reviewer: codex`, and `rule_version`. Do not accept by score or keyword alone. Review may stop early only after the explicitly accepted pool satisfies the preferred total and every quota; omitted ready packets remain audited as `ready_unreviewed` in `pending-review.csv` and can never enter the frozen selection.

`review corpus` verifies the request, candidate, evidence, and coverage hashes; rejects unknown IDs, duplicate decisions, stale hashes, missing explanations, and acceptance without title-and-abstract evidence; and revalidates an existing frozen selection on every rerun. It writes `reviewed-candidates.jsonl`, `pending-review.csv`, `selected-papers.jsonl`, and `selection-manifest.json`. The selection manifest hashes both the normalized specification and selected list; edit neither file before acquisition.

Acquisition verifies that frozen hash, writes `selection-binding.json` before the first publisher call, processes only `selected-papers.jsonl`, and never changes the selection. It writes verified pairs, `acquisition-manifest.jsonl`, `manual-download.csv`, `retryable-downloads.csv`, and `delivery-manifest.json`. A known access or paper-level failure does not stop unrelated selections. Corrupt ledgers and unbound or unverified reserved artifacts are rejected instead of overwritten.

Research is a resumable four-stage workflow. `discover research` runs the four query passes across configured search APIs, performs bounded backward/forward/related graph expansion, and writes `research-candidates.jsonl`, `citation-graph.json`, and `research-run.json`. Optional provider failures remain sanitized diagnostics; they do not erase successful results from other sources.

Codex must inspect every research candidate packet and create one row conforming to `schemas/research-review-decision.schema.json`. `review research` rejects stale candidate hashes, unknown claims, omitted explanations, non-Codex reviewers, duplicate decisions, and selections above `analysis.max_full_text_papers`. It freezes a selection only when every candidate has an explicit include/exclude decision, then binds both the normalized decisions and review manifest by SHA-256.

`acquire research` reuses the standard official publisher acquisition workflow. It never substitutes metadata APIs or repositories for the official PDF/BibTeX pair. Delivered PDFs are parsed through the content-addressed MinerU cache and recorded in `full-text-manifest.jsonl`; inaccessible publishers and parse failures stay pending so the same run can resume. Inspect both `acquisition_pending` and `parsing_pending`; the top-level status names the earliest unfinished gate so a manual publisher item is never hidden by a parser or evidence task.

After reading each parsed closest paper, Codex must create one row conforming to `schemas/research-evidence-review.schema.json`. `evidence research` verifies the selected paper ID, PDF SHA-256, Markdown SHA-256, claim IDs, relation/read-scope contract, and that every full-text excerpt occurs in the bound Markdown. It then fills `evidence-map.md`, `nearest-work-matrix.csv`, `claim-coverage.csv`, and `gap-analysis.md`. A run is `complete` only when every frozen paper has a completed full-text evidence review; unresolved claims remain explicitly unresolved and never become automatic novelty claims.

Use repeatable `--defer-host <exact-hostname>` options when a publisher must not be contacted during the current run. Matching is exact and case-insensitive: already hash-verified deliveries remain delivered, while undelivered records for those hosts enter `manual-download.csv` as `access_required`. Never remove deferred records from the frozen selection.

For a queued manual item, use the selection ID rather than copying editable CSV metadata:

```powershell
python "$skill/scripts/arp.py" manual-fetch `
  --selection <discovery-run\selection-manifest.json> --key <selection-id> `
  --output <delivery-root> --watch $HOME\Downloads
```

The user downloads from the official page, and the command verifies the local PDF/BibTeX pair against the frozen identity before filling its reserved paths.

Read [corpus mode](corpus-mode.md) or [research mode](research-mode.md) before running the corresponding mode. Read [source policies](source-policies.md) before changing a publisher contract and [credentials and cache](credentials-and-cache.md) before institutional access or MinerU. Use `arp schema <name.json>` for the authoritative runtime schema; bundled schema files are consultation snapshots.

## Markdown policy

`acquire research` uses a seven-day SHA-256 MinerU cache for internal reading. Do not copy that Markdown into publisher delivery. Export it only after the user explicitly requests and approves a destination:

```powershell
python "$skill/scripts/arp.py" export-md --pdf <paper.pdf> --output <directory>
```

## Completion rules

- Preserve publisher BibTeX verbatim; never generate or repair a citation with an LLM.
- Verify DOI, title, year, author scope, and venue against official metadata.
- Keep ambiguous, wrong-track, low-confidence, or mismatched papers out of automatic delivery.
- Report quota shortfalls instead of lowering screening thresholds.
- Treat title and abstract as corpus relevance evidence; keywords are optional and full text is not required. Direct support or contradiction in research mode requires full text with a section or page and a short excerpt.
- Ordinary fetch, manual fetch, corpus discovery, and corpus acquisition produce no Markdown.

## Hard stops

- Never print, log, summarize, or commit credentials, API keys, tokens, cookies, browser storage, or decrypted values.
- Release an IEEE credential only when the current hostname exactly equals the credential host in the current user's institution profile; stop on any other host, CAPTCHA, OTP, or incomplete login.
- Never treat a successful CARSI/IdP login as an IEEE session. Visit the configured resource gateway and require an exact IEEE return before requesting the PDF.
- Never automate ScienceDirect pages, submit its organization login, attach to the user's normal Chrome, read a Chrome profile, or export Cookie/session data. User authorization does not relax this boundary.
- Never use Crossref, OpenAlex, Semantic Scholar, a mirror, or generated BibTeX as the final citation artifact.
- Never bypass publisher/institution access controls, publish partial MinerU output, or overwrite a delivery without identity and hash validation.

For ScienceDirect, an Article Retrieval API 403 is not retried with browser cookies or scripted login. Use `manual-fetch`: the user downloads from the authorized official page and the CLI handles only local artifacts afterward.
