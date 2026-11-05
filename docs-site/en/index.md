# Acquire Research Papers

Acquire Research Papers is an agent skill and deterministic CLI for paper acquisition and library management. Codex, Claude Code, Kiro IDE, and Kiro CLI share the same skill:

- fetch a known paper from its DOI or official publisher page;
- build an auditable corpus for specified venues, years, topics, and quotas;
- prepare and carry out literature research for nearest work, claim evidence, Related Work, or gap analysis;
- audit, update, import, and organize local PDF/BibTeX libraries with reviewable plans and backups;
- discover an author's publications with explicit identity, date, and source-coverage evidence.

A completed acquisition is an identity-verified pair: the official publisher PDF and the publisher's raw BibTeX export. Crossref, OpenAlex, and Semantic Scholar can discover and enrich candidates, but they never replace those official artifacts. The project does not use mirrors, generate citations with an LLM, or bypass publisher access controls.

[Install](install.md){ .md-button .md-button--primary } [Quick start](quick-start.md){ .md-button } [Latest release](https://github.com/EnosElinsa/acquire-research-papers/releases/latest){ .md-button }

## Choose the workflow

| Your task | Workflow | What you get |
| --- | --- | --- |
| You have a DOI or official URL | `fetch` | One verified PDF/BibTeX pair, or an actionable access result |
| You need institution access or a different institution | `config setup ieee` → `config ieee login/doctor` | A named isolated profile, manual login by default, and separate authentication/download diagnostics |
| You have an existing PDF/BibTeX folder | `library audit/update/import/organize` → `library apply` | Version evidence, paired filenames, native citation bytes, a hash-bound change plan, and backups |
| You want an author's publication list or missing local papers | `discover author` | Formal, early-access, and preprint groups with identity ambiguity and source-coverage limits |
| You need papers from specified venues, years, and topics | `discover corpus` → agent review → `review corpus` → `acquire corpus` | Coverage evidence, a frozen selection, verified deliveries, and manual/retry queues |
| A publisher requires authorized user interaction | `manual-fetch` (`--queue` for a whole manual-download queue) | The official files you download are taken over locally, identified, verified, and placed in the reserved delivery paths |
| A command runs longer than your agent's command timeout | `--background <job-dir>` → `job status` (`job list` for all jobs) | The command runs in its own process; status reports progress and its final result |
| You need nearest work, claim citations, Related Work, or a gap check | `discover research` → `review research` → `acquire research` → `evidence research` | A citation graph, frozen closest-paper set, verified full text, and claim-level evidence reports |
| You explicitly need PDF-to-Markdown | `export-md` | A successful MinerU result exported on request; Markdown is never part of ordinary acquisition |

The corpus path is intentionally separated into four stages:

```text
scope and quotas
    → enumerate venue/year slices
    → enrich metadata and review title + abstract
    → freeze the selected papers
    → acquire official PDF/BibTeX pairs
        ├─ delivered
        ├─ manual_required
        └─ retryable
```

The executing agent is part of the workflow. The CLI validates, checkpoints, freezes, and acquires deterministic artifacts; the agent translates the user's request into explicit inputs and makes the recorded semantic review decisions.

## Capabilities and composition

Identity resolution, discovery, metadata enrichment, exact collection merge/compare, agent review, immutable selection, acquisition, local verification, standalone PDF parsing, evidence validation, library operations, and structured export can run independently. Existing corpus/research/author entrypoints remain available. See [capability contracts](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/references/capabilities.md) and [composition recipes](https://github.com/EnosElinsa/acquire-research-papers/blob/main/skills/acquire-research-papers/examples/README.md), each with inputs, expected results, recovery, and limits. These are compositions, not new kernel task types or an agent orchestrator.

New reviews use `schema_version: 2`, the actual host in `reviewer` and `executor.host`, and only available model/version metadata. Legacy Codex v1 reviews remain readable without rewriting their bytes or hashes. Capability commands support optional `--run` records and `arp run status --run <directory>`; legacy runs retain their original manifests and recovery commands. Standalone `parse` accepts PDF without BibTeX while retaining user-supplied trust. Structured `export --format markdown` differs from cached full-text `export-md`.

## Where to go next

- New to the project: [install](install.md), then [configure only what your task needs](configuration.md), then follow the [quick start](quick-start.md).
- Planning a bounded collection of papers: [corpus discovery](corpus.md) and [acquisition](acquisition.md).
- Checking prior work or a novelty claim: [literature research](research.md).
- Deciding whether a source fits your task: [source support](sources.md) and [trust and limitations](trust.md).
