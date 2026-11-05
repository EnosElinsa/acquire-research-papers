# Quick start

The examples assume `$skill` holds the installed skill directory, as set up in [Install](install.md):

```powershell
$skill = Join-Path $env:USERPROFILE ".agents/skills/acquire-research-papers"
```

## Fetch one known paper

```powershell
python "$skill/scripts/arp.py" fetch `
  --input "https://aclanthology.org/2024.acl-long.1/" `
  --output "C:\Research\papers"
```

Use the output only when the JSON status is `delivered`. A title alone must first be resolved through discovery; the fetch command will not guess between similarly named papers.

## Build a topic corpus

A user normally describes the task in plain language and lets the executing agent create the corpus specification. This compact example shows what is made explicit:

```yaml
schema_version: 1
mode: corpus
name: llm-agent-and-evolutionary-computation
target:
  minimum: 20
  preferred: 30
  maximum: 30
scope:
  venues:
    - name: "Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)"
      short_name: ACL
      publisher: ACL
      kind: conference
      years: [2025]
    - name: IEEE Transactions on Evolutionary Computation
      short_name: TEVC
      publisher: IEEE TEVC
      kind: journal
      issn: [1089-778X, 1941-0026]
      years: [2024, 2025]
  years:
    include: [2025, 2024]
    priority: [2025, 2024]
  publication_types:
    include: [full, journal-article]
  topics:
    include:
      - large language model multi-agent
      - evolutionary optimization
    synonyms:
      - agent collaboration
      - LLM-guided search
    exclude:
      - editorial
      - correction
quotas:
  groups:
    - name: ACL
      minimum: 10
      venues:
        - "Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)"
    - name: TEVC
      minimum: 10
      venues:
        - IEEE Transactions on Evolutionary Computation
delivery:
  require_pdf: true
  require_official_bibtex: true
  export_markdown: false
  profile: numbered
  naming_template: "papers/{publisher}/{number}.{ext}"
```

Run discovery first:

```powershell
python "$skill/scripts/arp.py" discover corpus --progress `
  --spec .\corpus.yaml --output C:\Research\corpus-run
```

The executing agent then reads `evidence-packets.jsonl`, reviews title and abstract evidence, and writes hash-bound decisions. Import those decisions and freeze the selection:

```powershell
python "$skill/scripts/arp.py" review corpus `
  --run C:\Research\corpus-run `
  --decisions C:\Research\corpus-run\review-decisions.jsonl
```

Acquire only the frozen selection:

```powershell
python "$skill/scripts/arp.py" acquire corpus `
  --selection C:\Research\corpus-run\selection-manifest.json `
  --output C:\Research\corpus-delivery
```

[Corpus discovery](corpus.md) explains each stage and the pending states you will see.

## Prepare a literature-research run

```yaml
schema_version: 1
mode: research
question_type: gap-analysis
research_question: Has prior work jointly optimized this scenario and mechanism?
work_under_review:
  scenario: multi-agent edge computing
  mechanism: LLM-guided evolutionary optimization
  decisions: [task allocation, agent communication]
  objectives: [latency, solution quality]
  constraints: [limited communication budget]
seed_papers: []
analysis:
  max_full_text_papers: 20
  graph_seed_limit: 3
  graph_neighbors_per_direction: 25
scope:
  years: [2023, 2024, 2025, 2026]
delivery:
  write_narrative: false
  export_markdown: false
```

```powershell
python "$skill/scripts/arp.py" discover research `
  --brief .\research-brief.yaml --output C:\Research\literature-review
```

Discovery returns `status: review_required`. Read its `saturation_signals` and `next_actions` first: they say whether to broaden the brief or widen the citation graph before review (see [literature research](research.md#search-saturation)). The executing agent then reviews the hash-bound candidates, freezes the closest papers, acquires their official files, reads the MinerU parses, and imports evidence:

```powershell
python "$skill/scripts/arp.py" review research `
  --run C:\Research\literature-review --decisions .\research-review.jsonl
python "$skill/scripts/arp.py" acquire research `
  --run C:\Research\literature-review
python "$skill/scripts/arp.py" evidence research `
  --run C:\Research\literature-review --records .\evidence-review.jsonl
```

The review and evidence JSONL files are produced by the executing agent from the immutable packets and parsed full text, using the public schemas in [`schemas/`](https://github.com/EnosElinsa/acquire-research-papers/tree/main/schemas). A final `status: complete` means every paper in the frozen closest-paper set was reviewed; it does not claim that every paper in the world was found or that novelty is universally proven.
