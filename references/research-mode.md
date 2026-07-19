# Research mode

Use this reference for gap analysis, nearest-work search, claim citations, citation verification, and Related Work research.

## Plan four complementary passes

Create a `ResearchBrief` conforming to `schemas/research-brief.schema.json`, then execute all four passes:

1. direct terminology and close synonyms;
2. scenario, mechanism, decisions, objectives, and constraints in decomposed combinations;
3. backward references, forward citations, and related-work graph expansion from seeds;
4. falsification queries seeking prior, equivalent, or counterexample work that would invalidate the proposed gap.

Repeat until new searches stop producing materially different mechanisms, recent and classic work are covered, closest papers have been read in full, and unresolved boundary papers cannot change the main judgment.

## Acquire before claiming

Metadata and abstracts nominate papers. Acquire the official PDF and official BibTeX pair for final candidates. For internal reading, a selected PDF may be parsed through the seven-day MinerU cache. The cache is analysis state, not a delivery artifact.

Do not export the cached Markdown unless the user explicitly asks for Markdown. Do not draft manuscript prose unless `delivery.write_narrative` is explicitly true or the user directly asks for prose.

## Record evidence

Allowed relations are:

- `direct-support`;
- `indirect-support`;
- `qualifies`;
- `contradicts`;
- `background`.

Every record identifies the claim/comparison dimension, paper, read scope, relation, strength, explanation, and uncertainty. `direct-support` and `contradicts` require a full-text read, a section or page location, and a short exact excerpt. Abstract-only records may be background or leads; they cannot directly establish a claim.

Keep excerpts short. Use them to anchor reasoning, not to reproduce the paper.

## Deliver an evidence package

The default package contains:

- `research-plan.json`;
- `research-manifest.csv`;
- `pending-review.csv`;
- `evidence-map.md`;
- `nearest-work-matrix.csv`;
- `gap-analysis.md` when applicable.

A gap conclusion must name the searched scope, list the closest counterexamples, disclose incomplete full-text checks, and use bounded wording such as "within the searched scope." The evidence report is not manuscript prose.
