# Related Work and claim evidence

Input: copy [related-work.yaml](inputs/related-work.yaml), supply the comparison question, named claims, available seed identities, scope and full-text budget. Narrative writing and Markdown export remain false unless the user requests them.

```text
arp discover research --brief <work>/related-work.yaml --output <work>/research
arp review research --run <work>/research --decisions <work>/candidate-review.jsonl
arp acquire research --run <work>/research
arp evidence research --run <work>/research --records <work>/evidence-review.jsonl
```

Between discovery and selection, the executing agent reads every immutable candidate packet and writes include/exclude decisions with actual hashes and v2 host provenance. After acquisition/parsing, read each selected full text and create claim-relation evidence from its exact PDF/Markdown hashes. Direct support or contradiction needs a section/page and short exact excerpt. Read `arp schema research-review-decision.schema.json` and `arp schema research-evidence-review.schema.json`.

Expected output: search/graph evidence, a frozen closest-paper set, official PDF/raw BibTeX pairs, an internal parse cache, evidence map, comparison matrix and claim coverage. A research report is not automatically manuscript prose.

Recovery: inspect separate `acquisition_pending` and `parsing_pending` counts. Import a queued user-downloaded pair with `manual-fetch --selection <work>/research/selection/selection-manifest.json --key <id> --output <work>/research/acquisition --pdf <pdf> --bibtex <bib> --no-open`, then rerun `acquire research`. Retry parser configuration/rate limits without dropping the paper. Preserve unchanged selection and artifact hashes.

Independent alternative: `parse --pdf <local.pdf> --output <work>/parse.json --run <work>/parse-run` works without BibTeX, followed by `evidence validate` against that result. Its source trust remains user-supplied; it does not complete official acquisition. `export --format markdown` formats structured records and does not export cached full text.

Limits: metadata/abstracts nominate candidates; they are not full-text support. Inaccessible or insufficient text remains unresolved. See [research mode](../references/research-mode.md).
