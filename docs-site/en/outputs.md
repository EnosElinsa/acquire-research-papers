# Outputs

Read the CLI result for current status, counts, next actions and available paths. An absent optional path is JSON `null`. Keep machine state for recovery; normally read only the report and nonempty action queues.

| Workflow / stage | State to retain | Human result / optional export |
| --- | --- | --- |
| Single paper | Verified PDF, raw publisher BibTeX and provenance | The verified pair; no report tree |
| Corpus discovery | Request, `coverage.jsonl`, candidates, evidence packets, discovery errors and manifest | `pending-metadata.csv` only when blocked metadata exists |
| Corpus review | Reviewed candidates, `selected-papers.jsonl`, selection and review manifests | `pending-review.csv` stays hash-bound, including an empty completed queue |
| Corpus acquisition | Acquisition ledger, selection binding, delivery manifest and official pairs | `paper-manifest.csv`; manual/retry queues only when nonempty |
| Research discovery | `research-plan.json`, `research-candidates.jsonl`, `citation-graph.json`, `search-saturation.json`, `research-run.json` | No evidence/gap reports at this stage |
| Research review / full text | Reviewed decisions, frozen selection, phase manifests, `full-text-manifest.jsonl` and internal parse cache | Nonempty review/download queues; status separates acquisition from parsing |
| Research evidence | `validated-evidence-reviews.jsonl` and `research-evidence.json` | One `reports/report.md`; `--export-csv` adds `papers.csv` and `claim-coverage.csv` |
| Author bibliography | `author-discovery.json` with source/identity/date evidence | `report.md`; `--export-csv` adds `author-discovery.csv` |
| Library audit | `audit.json` | `report.md`; nonempty manual queue; `--export-csv` adds `audit.csv` |
| Library update / import / organize | Reviewed plan, staged pairs, provenance, backups and apply journal | Review and apply the plan; keep backups for rollback |

New research runs record `output_version: 2`. Runs without it resume using their legacy report layout; frozen bytes and hashes are retained. In the new layout, the old research manifest and nearest-work matrix are combined into optional `papers.csv`; evidence map, claim status and the applicable bounded gap conclusion share `report.md`. Search provenance stays in `research-plan.json`. Re-running without CSV export clears only the named generated CSV views; resolved action queues disappear. Do not store hand-edited files under these generated names.

## Optional Markdown policy

`acquire research` parses selected PDFs into a seven-day SHA-256 MinerU cache for internal evidence review. The cached Markdown is analysis state, not a delivery artifact. Ordinary fetch, manual fetch, and corpus workflows do not produce Markdown. Export only after the user explicitly requests a destination:

```powershell
python "$skill/scripts/arp.py" export-md `
  --pdf .\paper.pdf --output C:\Research\markdown
```
