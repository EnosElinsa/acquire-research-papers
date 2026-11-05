# Research mode

Use this reference for gap analysis, nearest-work search, claim citations, citation verification, and Related Work research.

## Plan four complementary passes

Create a `ResearchBrief` conforming to `schemas/research-brief.schema.json`, then execute all four passes with `arp discover research --brief <brief.yaml> --output <research-run>` (`arp` means `python <skill-directory>/scripts/arp.py`):

1. direct terminology and close synonyms;
2. scenario, mechanism, decisions, objectives, and constraints in decomposed combinations;
3. backward references, forward citations, and related-work graph expansion from seeds;
4. falsification queries seeking prior, equivalent, or counterexample work that would invalidate the proposed gap.

Repeat until new searches stop producing materially different mechanisms, recent and classic work are covered, closest papers have been read in full, and unresolved boundary papers cannot change the main judgment.

Configured Semantic Scholar and OpenAlex clients join Crossref as research searchers. Semantic Scholar performs references, citations, and related-paper expansion; configured OpenAlex adds its citation relationships. `citation-graph.json` records the applied seed and neighbor limits, expanded seeds, and seeds skipped by the bound. Provider failures are recorded by phase and exception class without copying response bodies, keys, or signed query strings.

`search-saturation.json` (named in `research-run.json` as `search_saturation`) says whether the search was still finding new papers when it stopped. `query_passes` and `citation_frontier` list each step's in-scope results and how many were new; `coverage` gives the year spread (recent = the last three scope years), papers cited at least 100 times, and abstracts; `boundary_papers` lists candidates found by a single route or without an abstract. Act on `signals` before review: `search_still_growing` (the last query pass still added at least three papers and 30% of its results) means broaden the brief with synonyms, older terms, or venues; `citation_frontier_growing` means raise `analysis.graph_seed_limit` or `analysis.graph_neighbors_per_direction`; `seeds_not_expanded`, `candidate_limit_reached`, `provider_failures`, `no_recent_work`, and `no_earlier_work` are self-describing. Rerun discovery into a new directory with the changed brief. `stable_within_bounds` means only that this run's own queries and bounds stopped adding papers; never report it as recall or as proof that no other work exists. `discover research` prints the signals and their `next_actions`, and the evidence report has a "Search saturation" section.

Discovery writes an immutable `research-candidates.jsonl` snapshot, `citation-graph.json`, and `research-run.json`. Do not edit them. Review every candidate and write one JSONL decision per packet using `schemas/research-review-decision.schema.json`, preserving `candidate_id` and `candidate_sha256`. Run:

```text
arp review research --run <research-run> --decisions <research-review.jsonl>
```

The selection freezes only after every candidate has an explicit include/exclude decision by the executing agent. New records use `schema_version: 2`, actual-host `reviewer` and matching `executor.host`; model/version are included only when available. Legacy Codex v1 reviews remain readable unchanged. The normalized decision JSONL and review manifest are SHA-256-bound into that selection and rechecked before acquisition and evidence import. Keep only the closest papers needed to test the claims, within `analysis.max_full_text_papers`.

## Acquire before claiming

Metadata and abstracts nominate papers. Acquire the official PDF and official BibTeX pair for final candidates:

```text
arp acquire research --run <research-run>
```

This command reuses the frozen-selection acquisition workflow, then parses each verified PDF through the seven-day MinerU cache. `full-text-manifest.jsonl` binds the selection ID, official PDF SHA-256, cached Markdown SHA-256, parser mode, and pending reason. Rerunning reuses verified publisher artifacts and content-addressed parses. A manual publisher item remains selected and pending rather than being silently dropped. The result reports separate `acquisition_pending` and `parsing_pending` counts; its top-level status points to the earliest unfinished gate: missing publisher files, then failed parsing, then evidence review.

For papers listed in `acquisition/manual-download.csv`, import the user-authorized official pairs into the same acquisition root, then resume. `--queue` handles every listed paper in one session (see [corpus mode](corpus-mode.md#review-output)); `--key` imports one:

```text
arp manual-fetch --selection <research-run>/selection/selection-manifest.json --queue --output <research-run>/acquisition --from <folder-with-downloads>
arp manual-fetch --selection <research-run>/selection/selection-manifest.json --key <selection-id> --output <research-run>/acquisition --pdf <official.pdf> --bibtex <official.bib> --no-open
arp acquire research --run <research-run>
```

Resume accepts the pair only when the reserved paths, manual provenance, selection ID, metadata identity, and recorded file hashes all verify.

Do not export the cached Markdown unless the user explicitly asks for Markdown. Do not draft manuscript prose unless `delivery.write_narrative` is explicitly true or the user directly asks for prose.

## Record evidence

Allowed relations are:

- `direct-support`;
- `indirect-support`;
- `qualifies`;
- `contradicts`;
- `background`.

Every record identifies the claim/comparison dimension, paper, read scope, relation, strength, explanation, and uncertainty. Final `evidence research` records must come from the hash-bound full text. `direct-support` and `contradicts` additionally require a section or page location and a short exact excerpt. Abstract matches remain discovery leads and cannot be imported as final claim evidence.

Keep excerpts short. Use them to anchor reasoning, not to reproduce the paper.

Create one evidence-review row for every frozen paper using `schemas/research-evidence-review.schema.json`, then run:

```text
arp evidence research --run <research-run> --records <evidence-review.jsonl>
```

The importer rejects stale PDF hashes, changed Markdown, unknown claims, mismatched paper IDs, unsupported read scopes, and full-text excerpts not found in the bound Markdown. Use `insufficient-text` with an empty `records` array when the complete parse was read but cannot support a reliable claim record. Do not submit evidence for a paper that remains pending acquisition or parsing.

## Read the result

New discovery runs write five state files: `research-plan.json`, `research-candidates.jsonl`, `citation-graph.json`, `search-saturation.json`, and `research-run.json` (`output_version: 2`). Review and full-text phases append the audit and selection state required for recovery. Do not edit frozen artifacts.

After evidence import, read `reports/report.md`: paper review status, per-claim coverage, exact located evidence, pending work, and a bounded conclusion only for `gap-analysis`. Status `complete` means the frozen papers were reviewed; individual claims can remain unresolved. Search provenance stays in the root plan, rather than being copied into reports.

Add `--export-csv` to `evidence research` for `reports/papers.csv` and `reports/claim-coverage.csv`. The papers table combines the old research manifest and nearest-work matrix. Omitting the flag on a later import removes these generated views. Empty research review/evidence queues are omitted; optional CLI paths are null. Keep hand edits under different filenames.

Runs without `output_version` keep their legacy report layout on resume, including `evidence-map.md`, `nearest-work-matrix.csv`, `claim-coverage.csv`, and `gap-analysis.md`. No migration of immutable review state is required.

A gap conclusion names the searched scope, closest counterexamples, incomplete full-text checks and uncertainty. Use bounded wording such as "within the searched scope." The report is not manuscript prose. See [source coverage](sources.md) before interpreting search completeness.
