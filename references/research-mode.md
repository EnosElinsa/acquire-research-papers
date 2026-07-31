# Research mode

Use this reference for gap analysis, nearest-work search, claim citations, citation verification, and Related Work research.

## Plan four complementary passes

Create a `ResearchBrief` conforming to `schemas/research-brief.schema.json`, then execute all four passes with `arp discover research`:

1. direct terminology and close synonyms;
2. scenario, mechanism, decisions, objectives, and constraints in decomposed combinations;
3. backward references, forward citations, and related-work graph expansion from seeds;
4. falsification queries seeking prior, equivalent, or counterexample work that would invalidate the proposed gap.

Repeat until new searches stop producing materially different mechanisms, recent and classic work are covered, closest papers have been read in full, and unresolved boundary papers cannot change the main judgment.

Configured Semantic Scholar and OpenAlex clients join Crossref as research searchers. Semantic Scholar performs references, citations, and related-paper expansion; configured OpenAlex adds its citation relationships. `citation-graph.json` records the applied seed and neighbor limits, expanded seeds, and seeds skipped by the bound. Provider failures are recorded by phase and exception class without copying response bodies, keys, or signed query strings.

Discovery writes an immutable `research-candidates.jsonl` snapshot, `citation-graph.json`, and `research-run.json`. Do not edit them. Review every candidate and write one JSONL decision per packet using `schemas/research-review-decision.schema.json`, preserving `candidate_id` and `candidate_sha256`. Run:

```powershell
uv run --project $skill arp review research `
  --run <research-run> --decisions <research-review.jsonl>
```

The selection freezes only after every candidate has an explicit Codex include/exclude decision. The normalized decision JSONL and review manifest are SHA-256-bound into that selection and rechecked before acquisition and evidence import. Keep only the closest papers needed to test the claims, within `analysis.max_full_text_papers`.

## Acquire before claiming

Metadata and abstracts nominate papers. Acquire the official PDF and official BibTeX pair for final candidates:

```powershell
uv run --project $skill arp acquire research --run <research-run>
```

This command reuses the frozen-selection acquisition workflow, then parses each verified PDF through the seven-day MinerU cache. `full-text-manifest.jsonl` binds the selection ID, official PDF SHA-256, cached Markdown SHA-256, parser mode, and pending reason. Rerunning reuses verified publisher artifacts and content-addressed parses. A manual publisher item remains selected and pending rather than being silently dropped. The result reports separate `acquisition_pending` and `parsing_pending` counts; its top-level status points to the earliest unfinished gate: missing publisher files, then failed parsing, then evidence review.

For a paper listed in `acquisition/manual-download.csv`, import the user-authorized official pair into the same acquisition root, then resume:

```powershell
uv run --project $skill arp manual-fetch `
  --selection <research-run\selection\selection-manifest.json> `
  --key <selection-id> --output <research-run\acquisition> `
  --pdf <official.pdf> --bibtex <official.bib> --no-open
uv run --project $skill arp acquire research --run <research-run>
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

```powershell
uv run --project $skill arp evidence research `
  --run <research-run> --records <evidence-review.jsonl>
```

The importer rejects stale PDF hashes, changed Markdown, unknown claims, mismatched paper IDs, unsupported read scopes, and full-text excerpts not found in the bound Markdown. Use `insufficient-text` with an empty `records` array when the complete parse was read but cannot support a reliable claim record. Do not submit evidence for a paper that remains pending acquisition or parsing.

## Deliver an evidence package

The default package contains:

- `research-plan.json`;
- `research-candidates.jsonl` and `citation-graph.json`;
- `research-run.json`, `research-review.json`, and `full-text-run.json`;
- `research-manifest.csv`;
- `pending-review.csv`;
- `evidence-map.md`;
- `nearest-work-matrix.csv`;
- `claim-coverage.csv`;
- `gap-analysis.md` when applicable.

A gap conclusion must name the searched scope, list the closest counterexamples, disclose incomplete full-text checks, and use bounded wording such as "within the searched scope." The evidence report is not manuscript prose.
