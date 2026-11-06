# A few surveys on a topic across many journals

Use this recipe when the user wants a handful of surveys or representative papers on a topic, from many journals and years, and no fixed venue list. A corpus would first list every paper of every journal and year; this recipe searches by topic instead and reviews only the hits.

1. Search. Name the years, keep reviews only, and restrict the publisher or journals:

   ```text
   arp discover candidates --query "<topic words> survey" --query "<synonym> review" --year 2023 --year 2024 --year 2025 --year 2026 --type review --doi-prefix 10.1109 --title-term "<topic phrase>|<synonym>" --maximum 200 --progress --output <work>/candidates.json --run <work>/candidates-run
   ```

   `--preset T-RO --preset RA-L …` (or `--issn <ISSN>`) searches only those journals instead of a whole publisher; `arp sources` lists the presets. Each `--query` runs as its own search on Crossref, Semantic Scholar, and OpenAlex (OpenAlex needs a key), all at once. Semantic Scholar runs twice: a relevance search, and a bulk search that returns every paper whose title or abstract holds all the query's words, so a short query such as `path planning survey` finds more there than a long one. Write one `--query` per synonym or neighbouring term (motion planning, trajectory planning, navigation, obstacle avoidance), since no source expands synonyms. Crossref ranks keyword matches loosely; `--title-term` with the topic's key phrases (`a|b` accepts either) removes its noise. Semantic Scholar has no ISSN filter: it searches preset journals by name and is skipped for an `--issn` that belongs to no preset. `--type review` keeps works a source classifies as reviews and titles naming a survey, review, overview, tutorial, or state of the art. Records without an abstract get one from Semantic Scholar or OpenAlex by DOI when available.

   The output lists the best matches first. A record whose title and abstract hold none of a query's topic words is dropped (`dropped_unmatched` counts them); each kept record shows its score, matched terms, and the sources that found it in `provenance.search_match`.

2. Review. Read the title, venue, year, and abstract of every record in `candidates.json` and accept only papers that answer the user's request. Report the accepted DOIs with a one-line reason each. A filter match or a high score is a nomination, not an acceptance.

3. Acquire. Copy [doi-list.txt](inputs/doi-list.txt), put one accepted DOI per line, and fetch the list in one process, so one IEEE browser and one institution login serve every paper:

   ```text
   arp --background <work>/fetch-job fetch --input-file <work>/doi-list.txt --output <delivery> --layout flat
   arp job status --job <work>/fetch-job --wait 60
   ```

   `fetch-ledger.jsonl` in the delivery directory holds one row per paper. `--layout flat` writes `<short title>--<id>.pdf`, `.bib`, and `.provenance.json` directly into the delivery directory, which keeps Windows paths short.

Expected output: verified publisher PDF and raw BibTeX pairs with provenance, one ledger row per paper, and `manual-fetch` next actions for papers that need the user's download.

Recovery: a stopped or timed-out search still writes the candidates it found (`status: partial`, `interrupted: true`, or a `provider_timeout` diagnostic). Rerun the same command with the same `--output` (and `--run`): the records already found are kept and only the unfinished sources are asked again (`completed_sources`); add `--fresh` to search every source again, for example weeks later. Rerun the same `fetch --input-file` command with the same output for retryable papers; delivered papers are not fetched again.

Limits: keyword search is not exhaustive. Never call the result a complete list of surveys; say which queries, sources, years, and filters were searched (`filters` in the output).
