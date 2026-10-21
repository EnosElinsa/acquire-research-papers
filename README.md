# Acquire Research Papers

[简体中文](README.zh-CN.md)

[![CI](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml/badge.svg)](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/EnosElinsa/acquire-research-papers)](https://github.com/EnosElinsa/acquire-research-papers/releases/latest)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Acquire Research Papers is a shared agent skill and deterministic CLI for paper acquisition and library management:

- fetch a known paper from its DOI or official publisher page;
- build an auditable corpus for specified venues, years, topics, and quotas;
- prepare and carry out literature research for nearest work, claim evidence, Related Work, or gap analysis;
- audit, update, import, and organize local PDF/BibTeX libraries with reviewable plans and backups;
- discover an author's publications with explicit identity, date, and source-coverage evidence.

[Latest release](https://github.com/EnosElinsa/acquire-research-papers/releases/latest) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Help and feedback](SUPPORT.md) · [Security](SECURITY.md)

A completed acquisition is an identity-verified pair: the official publisher PDF and the publisher's raw BibTeX export. Crossref, OpenAlex, and Semantic Scholar can discover and enrich candidates, but they never replace those official artifacts. The project does not use mirrors, generate citations with an LLM, or bypass publisher access controls.

## Choose the workflow

| Your task | Workflow | What you get |
| --- | --- | --- |
| You have a DOI or official URL | `fetch` | One verified PDF/BibTeX pair, or an actionable access result |
| You need institution access or a different institution | `config setup ieee` → `config ieee login/doctor` | A named isolated profile, manual login by default, and separate authentication/download diagnostics |
| You have an existing PDF/BibTeX folder | `library audit/update/import/organize` → `library apply` | Version evidence, paired filenames, native citation bytes, a hash-bound change plan, and backups |
| You want an author's publication list or missing local papers | `discover author` | Formal, early-access, and preprint groups with identity ambiguity and source-coverage limits |
| You need papers from specified venues, years, and topics | `discover corpus` → agent review → `review corpus` → `acquire corpus` | Coverage evidence, a frozen selection, verified deliveries, and manual/retry queues |
| A publisher requires authorized user interaction | `manual-fetch` | The official files you download are taken over locally, identified, verified, and placed in the reserved delivery paths |
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

Identity resolution, discovery, metadata enrichment, exact collection merge/compare, agent review, immutable selection, acquisition, local verification, standalone PDF parsing, evidence validation, library operations, and structured export can run independently. Existing corpus/research/author entrypoints remain available. See [capability contracts](skills/acquire-research-papers/references/capabilities.md) and [composition recipes](skills/acquire-research-papers/examples/README.md), each with inputs, expected results, recovery, and limits. These are compositions, not new kernel task types or an agent orchestrator.

New reviews use `schema_version: 2`, the actual host in `reviewer` and `executor.host`, and only available model/version metadata. Legacy Codex v1 reviews remain readable without rewriting their bytes or hashes. Capability commands support optional `--run` records and `arp run status --run <directory>`; legacy runs retain their original manifests and recovery commands. Standalone `parse` accepts PDF without BibTeX while retaining user-supplied trust. Structured `export --format markdown` differs from cached full-text `export-md`.

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

The standard-library launcher reads `runtime.json`, downloads the fixed release wheel, verifies SHA-256, and installs it with uv into a separate cache. It never needs a developer checkout or installs development tools into the skill. File configuration and core commands support Windows/macOS/Linux. Current IEEE browser access and legacy DPAPI require Windows, PowerShell, and Node.js; live institutional access needs a separate check.

Update by rerunning the same Skills install command. Registries, credentials, caches, named institution profiles, and browser sessions live outside the installed skill. Use a separate delivery directory. Development builds can use the digest-verified local-wheel procedure in [CONTRIBUTING.md](CONTRIBUTING.md).

If your current skill directory is a Git developer checkout, preserve it. Do not point a third-party installer's overwrite operation at that directory. Build an export and use the repository's safe copy installer into a new directory; it refuses `.git` targets and keeps an explicit backup when replacing a clean previous thin skill. See [safe migration](CONTRIBUTING.md#safe-copy-and-checkout-migration).

### Host setup and checked support

Codex, Claude Code, Kiro IDE, and Kiro CLI share the same skill and pinned wheel. User skill directories are `~/.agents/skills/`, `~/.claude/skills/`, and `~/.kiro/skills/` respectively. Copy only the exported `acquire-research-papers/` folder. Kiro custom agents require explicit `skill://` resources; a [resource template](skills/acquire-research-papers/templates/kiro-agent.example.json) is included. See [host installation and official sources](skills/acquire-research-papers/references/hosts.md), checked on **October 20, 2026**.

Run `arp doctor --host <codex|claude-code|kiro-ide|kiro-cli> --skill-directory <actual-path>`. Its default local inventory reports Python/runtime/schema/configuration/dependency state. Host loading and institutional access remain unverified. `--check-host-version` explicitly runs the host executable's version command; `--remote-check` explicitly probes public Crossref reachability without credentials. Official format compatibility and synthetic CI are not live certification; Claude Code and Kiro interactive execution remain unverified until recorded.

### Release downloads and manual installation

The [v0.6.0 release](https://github.com/EnosElinsa/acquire-research-papers/releases/tag/v0.6.0) provides:

| Asset | Use |
| --- | --- |
| `acquire-research-papers-skill-0.6.0.zip` | Extract and copy the contained `acquire-research-papers/` folder to a new skill directory. It contains instructions, references, schemas, a launcher, and the pinned runtime manifest. |
| `acquire_research_papers-0.6.0-py3-none-any.whl` | Install the CLI independently with `uv tool install <wheel-path>`, or supply its absolute path as `ARP_LOCAL_WHEEL` when bootstrapping offline. The launcher still verifies the manifest digest. |
| `SHA256SUMS` | Compare downloaded asset hashes with `Get-FileHash <path> -Algorithm SHA256` on PowerShell or `sha256sum <path>` on Linux. |

Manual skill installation needs Python 3.11+ and uv. The launcher normally downloads its pinned wheel on first use; dependency installation also needs network access or a populated uv cache. Node.js is additionally required for IEEE browser access. Do not copy the source archive or a developer checkout into the skill directory. See [SUPPORT.md](SUPPORT.md) for bootstrap and migration troubleshooting.

## First use: configure only what this task needs

Start by asking which optional capabilities are already configured:

```powershell
python "$skill/scripts/arp.py" config status
```

The command returns capability booleans only; `--details` adds non-secret profile/history details. File values are read for presence and never emitted; legacy DPAPI status inspects scope shape without decrypting secrets. A `true` result means local configuration exists; it does not prove live API or publisher entitlement. Configure only a capability required by this task, then test it with a representative operation.

| Capability | Configure it when | Setup |
| --- | --- | --- |
| None | Public Crossref discovery, ACL discovery/acquisition, or IJCAI discovery/acquisition | No secret setup |
| Semantic Scholar | You want keyed candidate search, higher limits, and the first DOI abstract-enrichment pass | `arp config setup semantic_scholar` |
| OpenAlex | You want additional candidate search and a second DOI abstract-enrichment pass | `arp config setup openalex` |
| IEEE | You need institutional IEEE access; start with manual login and optionally enable a supported CARSI form | `arp config setup ieee` |
| Elsevier | You need official metadata resolution for the manual ScienceDirect handoff | `arp config setup elsevier` |
| MinerU | You need selected PDFs parsed for internal full-text analysis or explicit Markdown export | `arp config setup mineru` |

Secret prompts are interactive and non-echoing; institution names and official entry URLs are ordinary non-secret inputs. Never paste a password, API key, token, or cookie into chat, an agent message, a command argument, or a repository file. Local editing of the selected credential file outside the repository is supported. Provider updates are independent: adding OpenAlex does not replace IEEE, MinerU, Elsevier, or Semantic Scholar.

### Editable local credentials

New installations default to an editable local file backend outside the repository. Use `arp config init`, `arp config path`, and `arp config edit`; `config edit --profile <id>` opens one institution's file. The configuration root contains `config.toml`, `.env`, `institutions/<id>.json`, and `credentials/<id>.env`. `ARP_CONFIG_ROOT` overrides the platform configuration root; `ARP_DATA_ROOT` isolates runtime data. New data roots use the application's own name; detected legacy roots remain compatible.

The root `.env` contains `SEMANTIC_SCHOLAR_API_KEY`, `OPENALEX_API_KEY`, `ELSEVIER_API_KEY`, and `MINERU_TOKEN`. A selected institution file contains `INSTITUTION_USERNAME` and `INSTITUTION_PASSWORD`. [Empty templates](skills/acquire-research-papers/templates/.env.example) ship without values. Files are plaintext restricted to the current user: edit locally, keep private, and never commit them. Saving credentials does not enable automatic login.

API precedence is explicit process environment → one selected file; file selection is `--env-file` → `ARP_ENV_FILE` → default `.env`. There is no upward search, implicit dotenv merging, shell execution, or interpolation. Each command reads a snapshot; empty values are unconfigured. Institutions read only their selected profile file. Existing DPAPI installations stay legacy; explicit `arp config migrate --from dpapi` runs on the original Windows account, preserves the source, reports conflicting key names, and never overwrites conflicts. See [configuration details](skills/acquire-research-papers/references/credentials-and-cache.md).

## Named institutions, local libraries, and author discovery

The examples below use `arp` as shorthand for `python <skill-directory>/scripts/arp.py`.

```text
arp config setup ieee --profile my-institution --mode assisted
arp config ieee list
arp config ieee use my-institution
arp config ieee login --profile my-institution
arp config ieee doctor --profile my-institution --reference <IEEE-URL>
arp library audit <library-directory> --output <audit-directory>
arp library update <library-directory> --output <staging-directory>
arp library import <incoming-directory> --destination <library-directory> --output <plan.json>
arp library organize <library-directory> --output <plan.json>
arp library apply --plan <plan.json>
arp library apply --plan <plan.json> --rollback
arp discover author --spec <author.json> --output <discovery-directory>
```

IEEE supports `direct`, `assisted`, and explicit-contract `carsi` profiles, each with an isolated browser context. Profile configuration, identity-provider login, return to IEEE, a verified download, and institutional entitlement are separate states. An open-access download does not establish subscription entitlement. See [configuration](skills/acquire-research-papers/references/configuration.md).

Library audits report identities, duplicates, missing/ambiguous pairs, citation placement, and the PDF's independently evidenced version. A current BibTeX record does not prove the PDF is current. Registry metadata stays discovery evidence. Update stages official pairs; import/organize produce hash-bound plans; explicit apply checks hashes and keeps backups. Raw BibTeX bytes, BOM, encoding, and line endings are preserved. Optional `--metadata` inputs enable offline comparison; `update --verify-only` avoids acquisition. A bounded `--watch` observes user-downloaded ScienceDirect pairs and maintains one queue without automating a browser. See [library mode](skills/acquire-research-papers/references/library-mode.md).

Author specs accept identity IDs, affiliation/coauthors, date range, homepage, and a local library. Public ORCID, DBLP, homepage, and database records retain identity uncertainty and source errors. Exact DOI deduplication, formal/early-access/preprint groups, issue dates primary to online dates, and explicit version relations remain auditable; coverage is never claimed absolutely complete. `--records` supplies offline source evidence. See [author mode](skills/acquire-research-papers/references/author-mode.md).

## Quick start

### Fetch one known paper

```powershell
python "$skill/scripts/arp.py" fetch `
  --input "https://aclanthology.org/2024.acl-long.1/" `
  --output "C:\Research\papers"
```

Use the output only when the JSON status is `delivered`. A title alone must first be resolved through discovery; the fetch command will not guess between similarly named papers.

### Build a topic corpus

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

### Prepare a literature-research run

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

Discovery returns `status: review_required`. The executing agent then reviews the hash-bound candidates, freezes the closest papers, acquires their official files, reads the MinerU parses, and imports evidence:

```powershell
python "$skill/scripts/arp.py" review research `
  --run C:\Research\literature-review --decisions .\research-review.jsonl
python "$skill/scripts/arp.py" acquire research `
  --run C:\Research\literature-review
python "$skill/scripts/arp.py" evidence research `
  --run C:\Research\literature-review --records .\evidence-review.jsonl
```

The review and evidence JSONL files are produced by the executing agent from the immutable packets and parsed full text, using the public schemas in `schemas/`. A final `status: complete` means every paper in the frozen closest-paper set was reviewed; it does not claim that every paper in the world was found or that novelty is universally proven.

## How corpus discovery actually works

Corpus discovery is designed for bounded requests such as “papers from these venues, during these years, about these topics.” It uses the following process:

1. **Define the boundary.** The executing agent records exact venues, years, publication types, topics, exclusions, totals, and quotas.
2. **Enumerate before filtering.** ACL and IJCAI use official proceedings. Journals and identified conference collections use Crossref pagination by ISSN, collection DOI, venue, and year. OpenAlex and Semantic Scholar can add query-based candidates.
3. **Record coverage.** Every venue/year slice is marked complete, partial, or failed. A missing proceedings page or identifier becomes a diagnostic, not an empty result silently treated as complete.
4. **Merge and enrich.** Records are deduplicated primarily by DOI. Missing abstracts are looked up by DOI through Semantic Scholar and, when configured, OpenAlex. Field provenance remains attached to the candidate.
5. **Screen with evidence.** Deterministic rules reject wrong years, venues, tracks, types, and recognizable front matter. Keywords help nominate candidates, but acceptance requires the executing agent to judge both title and abstract and record a reason.
6. **Freeze after quotas are satisfied.** The selected list and normalized specification are hashed. Acquisition cannot add, remove, or replace papers afterward.

Two pending states are expected:

- `pending_abstract` means no trustworthy abstract was obtained. The paper is kept for later enrichment and cannot be automatically accepted from its title alone.
- `ready_unreviewed` (often seen as `decision_missing`) means the candidate has sufficient metadata but was not semantically reviewed, commonly because the preferred total and every quota were already satisfied. It cannot enter the selection.

Discovery artifacts are checkpoints. Rerunning the same directory reuses completed slices and retries incomplete providers rather than starting the whole task again.

## How literature research actually works

A defensible literature investigation needs more than one keyword query. The intended skill workflow uses four complementary passes:

1. **Direct terminology:** the research question, close synonyms, abbreviations, and older terms.
2. **Mechanism decomposition:** separate and recombine the scenario, mechanism, decisions, objectives, and constraints.
3. **Citation expansion:** inspect backward references, forward citations, Related Work, and graph-nearest papers from strong seeds.
4. **Falsification:** actively search for earlier, equivalent, or counterexample work that could invalidate the proposed gap.

Title and abstract are enough to nominate and triage candidates. A claim that a paper directly supports, contradicts, or already solves a research question requires a full-text read with a section or page and a short excerpt. Gap conclusions must be bounded to the searched scope and name the closest counterexamples.

Research mode is an explicit, resumable pipeline rather than an unattended one-command systematic review:

- `discover research` searches Crossref plus configured Semantic Scholar/OpenAlex sources, deduplicates by DOI, and executes bounded backward, forward, and related-paper expansion. Each optional provider can fail independently, leaving a sanitized diagnostic rather than erasing other results.
- `review research` requires one explicit agent include/exclude decision for every hash-bound candidate, then freezes only the closest papers selected for full-text checking. Its normalized decisions and review manifest are hash-bound into the selection.
- `acquire research` reuses the official publisher workflow, preserves manual and retry queues, and parses verified PDFs through the content-addressed MinerU cache. Separate acquisition/parsing pending counts keep mixed failures visible; the top-level status identifies the earliest unfinished gate.
- `evidence research` verifies paper IDs, PDF and Markdown hashes, claim IDs, read scope, locations, and excerpts before filling the evidence map, closest-work matrix, claim coverage, and bounded gap report.

Title and abstract still only nominate candidates. Direct support and contradiction require a full-text excerpt with a section or page. Papers blocked by publisher access or MinerU remain pending in the same frozen run; they are never silently removed or replaced.

## How acquisition works

Acquisition starts from a DOI, an exact official URL, or a hash-verified frozen selection. The selected publisher adapter must keep every request inside its approved host boundary. A successful delivery requires:

- a valid official PDF;
- the publisher's raw BibTeX export, preserved verbatim;
- matching DOI, title, year, venue, and author scope;
- provenance and SHA-256 hashes tying the files to the same paper.

Crossref, OpenAlex, Semantic Scholar, repositories, and mirrors never satisfy final delivery. An inaccessible paper remains in the frozen selection and is written to `manual-download.csv`; a transient network or rate-limit failure goes to `retryable-downloads.csv`. One failure does not stop unrelated papers.

The output directory is bound to one frozen selection before publisher contact. A rerun skips a delivered item only when every recorded path and hash still matches. For safety, an existing directory containing unbound PDFs, BibTeX files, or acquisition ledgers is rejected instead of being overwritten; use a clean delivery directory or a deliberate migration/import workflow.

## Source support and maturity

“Supported” is separated into discovery, acquisition, and live maturity:

Run `arp sources` or `arp sources --spec <corpus.yaml>` for offline capabilities and per-venue/year gaps. See [source inventory and acceptance criteria](skills/acquire-research-papers/references/sources.md). No priority venue list has been selected; existing ACL/IJCAI/IEEE/ACM/ScienceDirect scenarios do not imply coverage of all conferences and journals. Enumeration completion is relative to the chosen source; upstream omissions remain possible.

| Source | Discovery | PDF/BibTeX acquisition | Current maturity and fallback |
| --- | --- | --- | --- |
| Crossref | Primary venue/year enumeration and research search | No | Stable public metadata source; metadata completeness still varies by publisher |
| ACL Anthology | Official proceedings enumeration | Automatic | Mature and used in real corpus runs |
| IJCAI proceedings | Official proceedings and track parsing | Automatic | Mature and used in real corpus runs |
| IEEE Xplore | Candidates usually come from Crossref/OpenAlex/Semantic Scholar | Automatic with a configured CARSI institution profile | Generic profile-driven flow; live-tested end to end with one CARSI institution. Every additional institution requires first-use adaptation and a representative smoke test |
| ACM Digital Library | Usually Crossref collection enumeration plus optional query APIs | Conditional HTTP adapter | Works only when the official page and artifact endpoints allow the dedicated client. No production browser-backed ACM adapter exists yet; blocked pages become manual work |
| ScienceDirect | Crossref/OpenAlex/Semantic Scholar discovery; Elsevier API can resolve expected identity | Manual only | The user downloads in a normal authorized browser; the CLI verifies and imports the local pair. No scripted ScienceDirect login or browser automation |
| Semantic Scholar | Optional keyed candidate search, DOI enrichment, and citation/related graph expansion | No | Discovery and graph evidence only; provider failures remain diagnostics |
| OpenAlex | Optional candidate search, DOI enrichment, and citation graph expansion | No | Requires its optional API key; discovery and graph evidence only |
| MinerU | No | No | Optional seven-day full-text parsing cache; it is analysis support, not a paper source |
| Generic direct publisher adapter | Internal host-bounded adapter exists | Not enabled as a public production default | Requires an explicit approved-host configuration and productized setup before it should be advertised as general support |

## IEEE institutional access

IEEE uses a dedicated visible Chrome profile because authenticated access and PDF requests must share one isolated browser context. The workflow first tries the paper without reading credentials. If entitlement is missing, it:

1. enters the institution profile's exact CARSI IEEE resource gateway;
2. selects the exact configured institution option and writes and verifies its IdP entity ID;
3. releases the selected profile's credential only on the exact configured IdP hostname and submits it at most once;
4. handles either a single continue control or an accept/reject attribute-release page, never clicking reject;
5. revisits only the configured resource gateway when CARSI returns without IEEE entitlement;
6. requires the same context to return to the exact `ieeexplore.ieee.org` host before requesting PDF and BibTeX.

A configured accept/continue control is automatic by default. Pass `--no-accept-ieee-attribute-release` to keep the visible page available for manual completion.

### Adapting a new institution

The public script contains no university-name branch or shared credential. A new institution should be adapted through its profile first: exact CARSI option, entity ID, IdP hostname, accessible form labels, resource gateway, and continuation controls. Keep the visible browser open, use only sanitized stage/hostname diagnostics, and retry one representative paper after each correction.

Modify the generic browser script only when a visible page proves a new reusable page shape that cannot be represented by the profile. Add a regression fixture first. Preserve exact-host credential release, one credential submission, the three-visit gateway limit, shared cookies, reject-button prohibition, and query-value redaction.

## ScienceDirect manual handoff

ScienceDirect remains manual by design. Configure an Elsevier API key if the task needs official expected-identity resolution:

```powershell
python "$skill/scripts/arp.py" config setup elsevier
```

Start the watcher before downloading:

```powershell
python "$skill/scripts/arp.py" manual-fetch `
  --input "10.1016/j.asieco.2024.101746" `
  --watch "$HOME\Downloads" --output C:\Research\papers
```

The CLI opens only the canonical article page. The user completes organization login and downloads the official PDF plus raw BibTeX in a normal browser. The CLI observes only stable new or changed files, verifies the pair, and delivers it. It never controls ScienceDirect, reads the user's Chrome profile, exports cookies, or turns an Article Retrieval API 403 into scripted website login.

If both files already exist:

```powershell
python "$skill/scripts/arp.py" manual-fetch --input <DOI> `
  --pdf .\paper.pdf --bibtex .\citation.bib --output C:\Research\papers
```

For a frozen corpus item, use its immutable selection ID:

```powershell
python "$skill/scripts/arp.py" manual-fetch `
  --selection C:\Research\corpus-run\selection-manifest.json `
  --key <selection-id> --output C:\Research\corpus-delivery `
  --watch "$HOME\Downloads"
```

## Understand the outputs

Read the CLI result for current status, counts, next actions and available paths. An absent optional path is JSON `null`. Keep machine state for recovery; normally read only the report and nonempty action queues.

| Workflow / stage | State to retain | Human result / optional export |
| --- | --- | --- |
| Single paper | Verified PDF, raw publisher BibTeX and provenance | The verified pair; no report tree |
| Corpus discovery | Request, `coverage.jsonl`, candidates, evidence packets, discovery errors and manifest | `pending-metadata.csv` only when blocked metadata exists |
| Corpus review | Reviewed candidates, `selected-papers.jsonl`, selection and review manifests | `pending-review.csv` stays hash-bound, including an empty completed queue |
| Corpus acquisition | Acquisition ledger, selection binding, delivery manifest and official pairs | `paper-manifest.csv`; manual/retry queues only when nonempty |
| Research discovery | `research-plan.json`, `research-candidates.jsonl`, `citation-graph.json`, `research-run.json` | No evidence/gap reports at this stage |
| Research review / full text | Reviewed decisions, frozen selection, phase manifests, `full-text-manifest.jsonl` and internal parse cache | Nonempty review/download queues; status separates acquisition from parsing |
| Research evidence | `validated-evidence-reviews.jsonl` and `research-evidence.json` | One `reports/report.md`; `--export-csv` adds `papers.csv` and `claim-coverage.csv` |
| Author bibliography | `author-discovery.json` with source/identity/date evidence | `report.md`; `--export-csv` adds `author-discovery.csv` |
| Library audit | `audit.json` | `report.md`; nonempty manual queue; `--export-csv` adds `audit.csv` |
| Library update / import / organize | Reviewed plan, staged pairs, provenance, backups and apply journal | Review and apply the plan; keep backups for rollback |

New research runs record `output_version: 2`. Runs without it resume using their legacy report layout; frozen bytes and hashes are retained. In the new layout, the old research manifest and nearest-work matrix are combined into optional `papers.csv`; evidence map, claim status and the applicable bounded gap conclusion share `report.md`. Search provenance stays in `research-plan.json`. Re-running without CSV export clears only the named generated CSV views; resolved action queues disappear. Do not store hand-edited files under these generated names.

Use repeatable `--defer-host <exact-hostname>` options to defer a publisher for this run. Deferred records remain in the selection and enter the manual queue; verified prior deliveries remain delivered.

## Accuracy and trust boundaries

The project improves reliability in three different ways:

- **Coverage accountability:** venue/year enumeration and a coverage ledger are stronger than trusting the first page of keyword results. They still cannot guarantee that upstream indexes contain every paper.
- **Relevance accountability:** deterministic hard gates and prefiltering reduce noise, but an accepted paper requires a recorded agent judgment over title and abstract. This is more auditable than keyword-only acceptance, not a proof of universal semantic accuracy.
- **Artifact identity:** official-host boundaries, raw publisher BibTeX, metadata comparison, provenance, and hashes give the strongest guarantee in the system: the delivered files correspond to the frozen paper.

The repository has regression tests for its contracts and has completed real multi-venue corpus runs. It does not yet have a large, independently labeled cross-domain benchmark, so it must not advertise a measured precision/recall score. Missing abstracts, incomplete current-year indexes, ambiguous records, and boundary relevance judgments are reported rather than guessed.

## Current limitations

- The full IEEE/CARSI path has been live-validated with one CARSI institution. Every additional institution is profile-driven but still requires first-use observation and adaptation.
- Editable credential files and core commands are portable. Current IEEE browser integration and legacy DPAPI remain Windows-specific; Claude Code and Kiro interactive execution have not been live verified.
- IEEE journal discovery relies primarily on Crossref and optional metadata APIs; there is no official IEEE venue enumerator in the current release.
- ACM automation has no browser-backed production adapter. Official pages that block the HTTP client become manual items.
- ScienceDirect acquisition is manual only; the project intentionally does not automate organization login or the article page.
- Research mode is staged and requires explicit agent candidate and evidence decisions; it is not an unattended one-command systematic review.
- Citation-graph coverage is bounded by configured seeds, neighbor limits, provider coverage, and API availability; it cannot prove universal recall.
- A paper without a trustworthy abstract remains `pending_abstract`; title-only acceptance is forbidden.
- New or not-yet-published proceedings and inconsistent upstream metadata can leave coverage incomplete.
- `arp config status: true` confirms stored configuration shape, not live credentials, quota, subscription, or API entitlement.
- Large authenticated batches run conservatively and may be slow.
- Existing-folder library operations require an explicit reviewed hash-bound plan; unknown PDF/citation identity remains a manual review item.
- The internal generic publisher adapter is not a public plug-in system yet.
- No cross-domain labeled benchmark currently supports a numeric precision/recall claim.

## Roadmap

These are improvement priorities, not claims about current support.

### Near term

1. **Measure research-search saturation.** Add repeatable stopping diagnostics for new mechanisms, citation-frontier growth, classic/recent coverage, and unresolved boundary papers without turning them into false universal-recall claims.
2. **Improve IEEE institution diagnostics.** Extend the current named-profile doctor with clearer first-use adaptation and live access diagnostics while keeping secrets private.
3. **Productize ACM authorized access.** Design a dedicated visible, isolated, exact-host browser contract with the same fail-closed standards as IEEE; retain manual fallback when access or page shape is unknown.
4. **Extend safe delta acquisition.** Build on the existing library import/update plans to bind new frozen selections while preserving verified files.
5. **Expand composition guidance.** Build on the shipped recipes, input templates, and run summaries; evaluate optional init helpers after their contracts stabilize.

### Medium term

6. **Measure discovery quality.** Build labeled venue/topic fixtures and report coverage, precision, recall, pending-abstract rate, and reviewer disagreement by source and discipline.
7. **Expand official enumeration.** Add exact, auditable venue adapters where an official index or API exists, especially for IEEE and ACM collections, without weakening identifier requirements.
8. **Improve batch operations.** Add safe publisher-aware concurrency, progress snapshots, retry scheduling, and manual-queue batch handoff while preserving rate limits and shared-session safety.
9. **Expand checked portability.** Validate host integrations and IEEE browser workflows per operating system while retaining explicit file-credential setup and Windows DPAPI migration compatibility.
10. **Open a publisher plug-in contract.** Let users register exact approved hosts and tested page contracts for the generic adapter without accepting arbitrary redirects or generated citations.

ScienceDirect browser automation is deliberately not on the roadmap unless publisher policy and a safe official integration make it appropriate.

## Optional Markdown policy

`acquire research` parses selected PDFs into a seven-day SHA-256 MinerU cache for internal evidence review. The cached Markdown is analysis state, not a delivery artifact. Ordinary fetch, manual fetch, and corpus workflows do not produce Markdown. Export only after the user explicitly requests a destination:

```powershell
python "$skill/scripts/arp.py" export-md `
  --pdf .\paper.pdf --output C:\Research\markdown
```

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, Python/Node/PowerShell checks, wheel/skill builds, isolated installation, and release validation.

## Responsible use

Use institutional access only within the account and license terms that authorize the requested material. The project does not bypass publisher controls, redistribute acquired papers, automate prohibited publisher interactions, or weaken an institution's authentication flow.

Licensed under the [MIT License](LICENSE).
