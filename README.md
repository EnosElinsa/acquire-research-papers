# Acquire Research Papers

[简体中文](https://github.com/EnosElinsa/acquire-research-papers/blob/main/README.zh-CN.md)

[![CI](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml/badge.svg)](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml)
[![Weekly source check](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/source-check.yml/badge.svg)](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/source-check.yml)
[![Docs](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/docs.yml/badge.svg)](https://enoselinsa.github.io/acquire-research-papers/)
[![Release](https://img.shields.io/github/v/release/EnosElinsa/acquire-research-papers)](https://github.com/EnosElinsa/acquire-research-papers/releases/latest)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/EnosElinsa/acquire-research-papers/blob/main/LICENSE)

Acquire Research Papers is an agent skill and deterministic CLI for paper acquisition and library management. Codex, Claude Code, Kiro IDE, and Kiro CLI share the same skill:

- fetch a known paper from its DOI or official publisher page;
- build an auditable corpus for specified venues, years, topics, and quotas;
- prepare and carry out literature research for nearest work, claim evidence, Related Work, or gap analysis;
- audit, update, import, and organize local PDF/BibTeX libraries with reviewable plans and backups;
- discover an author's publications with explicit identity, date, and source-coverage evidence.

**[Documentation](https://enoselinsa.github.io/acquire-research-papers/)** · [Latest release](https://github.com/EnosElinsa/acquire-research-papers/releases/latest) · [Changelog](https://github.com/EnosElinsa/acquire-research-papers/blob/main/CHANGELOG.md) · [Contributing](https://github.com/EnosElinsa/acquire-research-papers/blob/main/CONTRIBUTING.md) · [Help and feedback](https://github.com/EnosElinsa/acquire-research-papers/blob/main/SUPPORT.md) · [Security](https://github.com/EnosElinsa/acquire-research-papers/blob/main/SECURITY.md)

A completed acquisition is an identity-verified pair: the official publisher PDF and the publisher's raw BibTeX export. Crossref, OpenAlex, and Semantic Scholar can discover and enrich candidates, but they never replace those official artifacts. The project does not use mirrors, generate citations with an LLM, or bypass publisher access controls.

This README is a summary. The [documentation site](https://enoselinsa.github.io/acquire-research-papers/) (English and [简体中文](https://enoselinsa.github.io/acquire-research-papers/zh/)) has the complete guides, specification examples, and output reference.

## Contents

- **Start:** [choose the workflow](#choose-the-workflow) · [install](#install) · [first use](#first-use-configure-only-what-this-task-needs) · [quick start](#quick-start)
- **How it works:** [corpus discovery](#how-corpus-discovery-actually-works) · [literature research](#how-literature-research-actually-works) · [sources](#source-support-and-maturity)
- **Scope and project:** [trust boundaries](#accuracy-and-trust-boundaries) · [limitations](#current-limitations) · [roadmap](#roadmap) · [development](#development) · [citation](#citation)

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

The executing agent is part of the workflow. The CLI validates, checkpoints, freezes, and acquires deterministic artifacts; the agent translates the user's request into explicit inputs and makes the recorded semantic review decisions.

## Install

Install the skill with the standard Skills installer (Node.js/npm required); no developer clone or development dependency sync is needed:

```text
npx skills add EnosElinsa/acquire-research-papers --skill acquire-research-papers -a codex -g
```

Use Python 3.11+ and [uv](https://docs.astral.sh/uv/). Resolve the actual directory returned by the installer; the shared default is normally `~/.agents/skills/acquire-research-papers`:

```powershell
$skill = Join-Path $env:USERPROFILE ".agents/skills/acquire-research-papers"
python "$skill/scripts/arp.py" --help
python "$skill/scripts/arp.py" config status
```

The standard-library launcher reads `runtime.json`, downloads the fixed release wheel, verifies SHA-256, and installs it with uv into a separate cache. File configuration and core commands support Windows/macOS/Linux. Current IEEE browser access and legacy DPAPI require Windows, PowerShell, and Node.js; on macOS and Linux, IEEE papers join the manual-download queue. Update by rerunning the same install command. [Install](https://enoselinsa.github.io/acquire-research-papers/install/) covers other hosts, `arp doctor`, and migrating from a developer checkout.

### Release downloads and manual installation

The [v0.15.0 release](https://github.com/EnosElinsa/acquire-research-papers/releases/tag/v0.15.0) provides:

| Asset | Use |
| --- | --- |
| `acquire-research-papers-skill-0.15.0.zip` | Extract and copy the contained `acquire-research-papers/` folder to a new skill directory. It contains instructions, references, schemas, a launcher, and the pinned runtime manifest. |
| `acquire_research_papers-0.15.0-py3-none-any.whl` | Install the CLI independently with `uv tool install <wheel-path>`, or supply its absolute path as `ARP_LOCAL_WHEEL` when bootstrapping offline. The launcher still verifies the manifest digest. |
| `SHA256SUMS` | Compare downloaded asset hashes with `Get-FileHash <path> -Algorithm SHA256` on PowerShell or `sha256sum <path>` on Linux. |

Do not copy the source archive or a developer checkout into the skill directory. See [SUPPORT.md](https://github.com/EnosElinsa/acquire-research-papers/blob/main/SUPPORT.md) for bootstrap and migration troubleshooting.

## First use: configure only what this task needs

Start by asking which optional capabilities are already configured:

```powershell
python "$skill/scripts/arp.py" config status
```

The command returns capability booleans only and never prints secret values. A `true` result means local configuration exists; it does not prove live API or publisher entitlement. Configure only a capability required by this task, then test it with a representative operation.

| Capability | Configure it when | Setup |
| --- | --- | --- |
| None | Public Crossref discovery; discovery and acquisition from the official ACL, IJCAI, AAAI, NeurIPS, ICLR (2024 on), PMLR, CVF, and USENIX archives; open-access Springer papers | No secret setup |
| Semantic Scholar | You want keyed candidate search, higher limits, and the first DOI abstract-enrichment pass | `arp config setup semantic_scholar` |
| OpenAlex | You need IEEE or ACM conferences enumerated through their OpenAlex series (INFOCOM, ICC, GLOBECOM, SIGCOMM, and others), additional candidate search, or a second DOI abstract-enrichment pass | `arp config setup openalex` |
| IEEE | You need institutional IEEE access; start with manual login and optionally enable a supported CARSI form | `arp config setup ieee` |
| Elsevier | You need official metadata resolution for the manual ScienceDirect handoff | `arp config setup elsevier` |
| MinerU | You need selected PDFs parsed for internal full-text analysis or explicit Markdown export | `arp config setup mineru` |

Secret prompts are interactive and non-echoing. Never paste a password, API key, token, or cookie into chat, an agent message, a command argument, or a repository file. [Configuration](https://enoselinsa.github.io/acquire-research-papers/configuration/) explains the editable credential files and named institution profiles.

## Quick start

Fetch one known paper:

```powershell
python "$skill/scripts/arp.py" fetch `
  --input "https://aclanthology.org/2024.acl-long.1/" `
  --output "C:\Research\papers"
```

Use the output only when the JSON status is `delivered`. A title alone must first be resolved through discovery; the fetch command will not guess between similarly named papers.

Corpus and research runs start from a specification or brief that the executing agent writes from your request. `arp` is shorthand for `python "$skill/scripts/arp.py"`:

```text
arp discover corpus --progress --spec corpus.yaml --output <corpus-run>
arp review corpus --run <corpus-run> --decisions <review-decisions.jsonl>
arp acquire corpus --selection <corpus-run>/selection-manifest.json --output <delivery>

arp discover research --brief research-brief.yaml --output <research-run>
arp review research --run <research-run> --decisions <research-review.jsonl>
arp acquire research --run <research-run>
arp evidence research --run <research-run> --records <evidence-review.jsonl>
```

The [quick start](https://enoselinsa.github.io/acquire-research-papers/quick-start/) has a complete corpus specification and research brief to copy.

## How corpus discovery actually works

Corpus discovery is designed for bounded requests such as “papers from these venues, during these years, about these topics.” It records the boundary, enumerates official indexes (ACL, IJCAI, NeurIPS, ICLR, PMLR, CVF, USENIX) or Crossref by ISSN, collection DOI, venue, and year, and marks every venue/year slice complete, partial, or failed. Records are deduplicated by DOI and enriched with abstracts. Keywords only nominate candidates: acceptance requires the executing agent to judge both title and abstract and record a reason. The selection is hashed and frozen before acquisition, which cannot add, remove, or replace papers.

Two pending states are expected:

- `pending_abstract` means no trustworthy abstract was obtained. The paper is kept for later enrichment and cannot be automatically accepted from its title alone.
- `ready_unreviewed` (often seen as `decision_missing`) means the candidate has sufficient metadata but was not semantically reviewed, commonly because the preferred total and every quota were already satisfied. It cannot enter the selection.

An inaccessible paper stays in the frozen selection and is written to `manual-download.csv`; a transient failure goes to `retryable-downloads.csv`. Reruns resume from checkpoints. See [corpus discovery](https://enoselinsa.github.io/acquire-research-papers/corpus/) and [acquisition](https://enoselinsa.github.io/acquire-research-papers/acquisition/).

## How literature research actually works

A defensible literature investigation needs more than one keyword query. The skill searches with four complementary passes (direct terminology, mechanism decomposition, citation expansion, and falsification) in an explicit, resumable pipeline:

- `discover research` searches Crossref plus configured Semantic Scholar/OpenAlex sources and expands a bounded citation graph into `citation-graph.json`. `search-saturation.json` records whether the last query passes and graph steps were still adding new papers, and its signals say whether to broaden the brief or widen the graph. Discovery returns `status: review_required`.
- `review research` requires one explicit agent include/exclude decision for every hash-bound candidate, then freezes the closest papers for full-text checking.
- `acquire research` reuses the official publisher workflow and parses verified PDFs through the MinerU cache.
- `evidence research` verifies paper IDs, hashes, claims, locations, and excerpts before writing the report; `--export-csv` adds `papers.csv` and `claim-coverage.csv`.

Title and abstract only nominate candidates. Direct support and contradiction require a full-text excerpt with a section or page, and gap conclusions are bounded to the searched scope. See [literature research](https://enoselinsa.github.io/acquire-research-papers/research/).

## Source support and maturity

| Source | Discovery | PDF/BibTeX acquisition |
| --- | --- | --- |
| Crossref | Venue/year enumeration and research search | No |
| ACL Anthology, IJCAI, NeurIPS, ICLR (2024 on), PMLR, CVF Open Access, USENIX | Official indexes with abstracts | Automatic |
| AAAI | Crossref with the AAAI ISSN | Automatic; AAAI's citation export has answered HTTP 520 since early November 2026 |
| Springer Link | Crossref/OpenAlex/Semantic Scholar | Automatic when this network has access |
| IEEE Xplore | Journals through Crossref, conferences through OpenAlex | Automatic with a configured CARSI institution profile |
| ACM Digital Library | Crossref collections | Manual while ACM challenges non-browser clients |
| ScienceDirect | Crossref/OpenAlex/Semantic Scholar | Manual only, verified and imported by the CLI |
| Semantic Scholar, OpenAlex | Optional search, enrichment, and citation graph | No |
| MinerU | No | No; optional full-text parsing cache |

The IEEE flow is generic and profile-driven; it has been live-tested end to end with one CARSI institution, and every additional institution requires first-use adaptation. Run `arp sources --spec <corpus.yaml>` for offline per-venue/year gaps. [Source support](https://enoselinsa.github.io/acquire-research-papers/sources/) has the full table with live-test results and the venue presets.

## Accuracy and trust boundaries

The project improves reliability in three different ways:

- **Coverage accountability:** venue/year enumeration and a coverage ledger are stronger than trusting the first page of keyword results. They still cannot guarantee that upstream indexes contain every paper.
- **Relevance accountability:** deterministic hard gates and prefiltering reduce noise, but an accepted paper requires a recorded agent judgment over title and abstract. This is more auditable than keyword-only acceptance, not a proof of universal semantic accuracy.
- **Artifact identity:** official-host boundaries, raw publisher BibTeX, metadata comparison, provenance, and hashes give the strongest guarantee in the system: the delivered files correspond to the frozen paper.

The repository has regression tests for its contracts and has completed real multi-venue corpus runs. It does not yet have a large, independently labeled cross-domain benchmark, so it must not advertise a measured precision/recall score. Missing abstracts, incomplete current-year indexes, ambiguous records, and boundary relevance judgments are reported rather than guessed.

## Current limitations

- The full IEEE/CARSI path has been live-validated with one CARSI institution; IEEE browser integration is Windows-only.
- ACM and ScienceDirect papers are manual downloads; the project does not automate organization login.
- Research mode is staged and requires explicit agent decisions; it is not an unattended one-command systematic review.
- Citation-graph coverage is bounded by seeds, neighbor limits, and provider coverage; neither the graph nor the saturation record proves universal recall.
- New proceedings and inconsistent upstream metadata can leave coverage incomplete.
- `arp config status: true` confirms stored configuration shape, not live credentials, quota, subscription, or API entitlement.
- Claude Code and Kiro interactive execution have not been live verified.

[Trust and limitations](https://enoselinsa.github.io/acquire-research-papers/trust/) lists every known limitation.

## Roadmap

Near-term priorities, not claims about current support: follow-up discovery that reuses a finished research run, clearer IEEE institution diagnostics, a dedicated ACM authorized-access contract, safe delta acquisition into existing libraries, and more composition guidance. See the [roadmap](https://enoselinsa.github.io/acquire-research-papers/roadmap/).

## Development

See [CONTRIBUTING.md](https://github.com/EnosElinsa/acquire-research-papers/blob/main/CONTRIBUTING.md) for development setup, Python/Node/PowerShell checks, wheel/skill builds, isolated installation, release validation, and the documentation site. Participation is governed by the [Code of Conduct](https://github.com/EnosElinsa/acquire-research-papers/blob/main/CODE_OF_CONDUCT.md); questions and bug reports go through [SUPPORT.md](https://github.com/EnosElinsa/acquire-research-papers/blob/main/SUPPORT.md), and vulnerabilities through [SECURITY.md](https://github.com/EnosElinsa/acquire-research-papers/blob/main/SECURITY.md).

## Citation

If this tool supports published research, cite the release you used. [CITATION.cff](https://github.com/EnosElinsa/acquire-research-papers/blob/main/CITATION.cff) holds the citation metadata; GitHub shows it as "Cite this repository" on the repository page.

## Responsible use

Use institutional access only within the account and license terms that authorize the requested material. The project does not bypass publisher controls, redistribute acquired papers, automate prohibited publisher interactions, or weaken an institution's authentication flow.

Licensed under the [MIT License](https://github.com/EnosElinsa/acquire-research-papers/blob/main/LICENSE).
