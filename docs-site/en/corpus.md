# Corpus discovery

Corpus discovery is designed for bounded requests such as “papers from these venues, during these years, about these topics.” The [quick start](quick-start.md#build-a-topic-corpus) shows a complete specification and the three commands.

## How corpus discovery works

1. **Define the boundary.** The executing agent records exact venues, years, publication types, topics, exclusions, totals, and quotas.
2. **Enumerate before filtering.** ACL, IJCAI, NeurIPS, ICLR (from 2024), the PMLR conferences (ICML, AISTATS, COLT, and others), CVF (CVPR, ICCV, WACV), and USENIX (Security, OSDI, NSDI, ATC, FAST) are read from their official indexes. Journals and identified conference collections use Crossref pagination by ISSN, collection DOI, venue, and year. OpenAlex and Semantic Scholar can add query-based candidates.
3. **Record coverage.** Every venue/year slice is marked complete, partial, or failed. A missing proceedings page or identifier becomes a diagnostic, not an empty result silently treated as complete.
4. **Merge and enrich.** Records are deduplicated primarily by DOI. Missing abstracts are looked up by DOI through Semantic Scholar and, when configured, OpenAlex. Field provenance remains attached to the candidate.
5. **Screen with evidence.** Deterministic rules reject wrong years, venues, tracks, types, and recognizable front matter. Keywords help nominate candidates, but acceptance requires the executing agent to judge both title and abstract and record a reason.
6. **Freeze after quotas are satisfied.** The selected list and normalized specification are hashed. Acquisition cannot add, remove, or replace papers afterward.

## Pending states

Two pending states are expected:

- `pending_abstract` means no trustworthy abstract was obtained. The paper is kept for later enrichment and cannot be automatically accepted from its title alone.
- `ready_unreviewed` (often seen as `decision_missing`) means the candidate has sufficient metadata but was not semantically reviewed, commonly because the preferred total and every quota were already satisfied. It cannot enter the selection.

## Checkpoints and reruns

Discovery artifacts are checkpoints. Rerunning the same directory reuses completed slices and retries incomplete providers rather than starting the whole task again. Slices that carry a `possible_upstream_lag` warning are read again, and missing abstracts are looked up again; finished slices are not fetched again.

Venue presets let a specification name a venue by its short name, such as `name: INFOCOM` or `name: IEEE TMC`; [source support](sources.md#venue-presets) lists what they cover. Run `arp sources --spec <corpus.yaml>` before discovery to see per-venue/year gaps offline.

After review, [acquisition](acquisition.md) delivers only the frozen selection. The [skill's corpus reference](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/corpus-mode.md) holds the complete agent-facing contract.

## A few surveys on a topic

A corpus lists every paper of every venue and year first. For a handful of surveys from many journals, search by topic instead:

```text
arp discover candidates --query "mobile robot path planning survey" --year 2024 --year 2025 --type review --doi-prefix 10.1109 --title-term "path planning|motion planning" --output candidates.json
```

The search runs on Crossref and Semantic Scholar without a key and on OpenAlex with one, all at once, within the years and filters; `--preset T-RO` or `--issn` limits it to named journals. Records whose title and abstract contain none of the query's topic words are dropped, and the rest come best match first. Rerunning the same command into the same output asks again only the sources that did not finish. The agent reviews the titles and abstracts, writes the accepted DOIs into a text file, and runs `arp fetch --input-file`. The [topic-survey recipe](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/examples/08-topic-surveys.md) has the full steps. Keyword search is not exhaustive; report the searched queries and filters with the result.
