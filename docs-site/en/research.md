# Literature research

A defensible literature investigation needs more than one keyword query. The [quick start](quick-start.md#prepare-a-literature-research-run) shows a complete brief and the four commands.

## Four search passes

The intended skill workflow uses four complementary passes:

1. **Direct terminology:** the research question, close synonyms, abbreviations, and older terms.
2. **Mechanism decomposition:** separate and recombine the scenario, mechanism, decisions, objectives, and constraints.
3. **Citation expansion:** inspect backward references, forward citations, Related Work, and graph-nearest papers from strong seeds.
4. **Falsification:** actively search for earlier, equivalent, or counterexample work that could invalidate the proposed gap.

Title and abstract are enough to nominate and triage candidates. A claim that a paper directly supports, contradicts, or already solves a research question requires a full-text read with a section or page and a short excerpt. Gap conclusions must be bounded to the searched scope and name the closest counterexamples.

## The staged pipeline

Research mode is an explicit, resumable pipeline rather than an unattended one-command systematic review:

- `discover research` searches Crossref plus configured Semantic Scholar/OpenAlex sources, deduplicates by DOI, and executes bounded backward, forward, and related-paper expansion. Each optional provider can fail independently, leaving a sanitized diagnostic rather than erasing other results. It writes `research-plan.json`, `research-candidates.jsonl`, `citation-graph.json`, `search-saturation.json`, and `research-run.json`, and returns `status: review_required`.
- `review research` requires one explicit agent include/exclude decision for every hash-bound candidate, then freezes only the closest papers selected for full-text checking. Its normalized decisions and review manifest are hash-bound into the selection.
- `acquire research` reuses the official publisher workflow, preserves manual and retry queues, and parses verified PDFs through the content-addressed MinerU cache. Separate acquisition/parsing pending counts keep mixed failures visible; the top-level status identifies the earliest unfinished gate.
- `evidence research` verifies paper IDs, PDF and Markdown hashes, claim IDs, read scope, locations, and excerpts before filling the evidence map, closest-work matrix, claim coverage, and bounded gap report. `--export-csv` adds `papers.csv` and `claim-coverage.csv`.

Title and abstract still only nominate candidates. Direct support and contradiction require a full-text excerpt with a section or page. Papers blocked by publisher access or MinerU remain pending in the same frozen run; they are never silently removed or replaced.

## Search saturation

`search-saturation.json` says whether the search was still finding new papers when it stopped. `discover research` prints its `saturation_signals` and `next_actions`, and the evidence report repeats them in a "Search saturation" section.

| Part of the record | What it holds |
| --- | --- |
| `query_passes` | Each query pass's in-scope results and how many of them were new |
| `citation_frontier` | The same for each citation-graph step (seed and direction), plus the seeds that `analysis.graph_seed_limit` left unexpanded |
| `coverage` | The year spread (recent means the last three scope years), papers cited at least 100 times, and how many candidates have an abstract |
| `boundary_papers` | Candidates found by a single search route or without an abstract |

Act on the signals before review:

| Signal | Meaning | What to do |
| --- | --- | --- |
| `search_still_growing` | The last query pass still added at least three papers and 30% of its results | Broaden the brief with synonyms, older terms, or venues |
| `citation_frontier_growing` | The last citation-graph step still added that many new papers | Raise `analysis.graph_seed_limit` or `analysis.graph_neighbors_per_direction` |
| `seeds_not_expanded` | Candidate seeds were skipped by the seed limit | Raise `analysis.graph_seed_limit` |
| `candidate_limit_reached` | The candidate list hit its maximum; lower-ranked papers were cut | Review the ranking or narrow the brief |
| `provider_failures` | A search or graph provider failed | Rerun later; its results are missing |
| `no_recent_work` / `no_earlier_work` | No candidate falls in the last three scope years, or every candidate does | Add current or older terminology and venues |
| `stable_within_bounds` | None of the growth or limit signals fired | Proceed to review |

Rerun discovery into a new directory with the changed brief. `stable_within_bounds` means only that this run's own queries and bounds stopped adding papers. Never report it as recall or as proof that no other work exists.

## Reference

The [skill's research reference](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/research-mode.md) holds the complete agent-facing contract, including the review and evidence record schemas.
