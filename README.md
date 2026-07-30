# Acquire Research Papers

[简体中文](README.zh-CN.md)

[![CI](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml/badge.svg)](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Acquire Research Papers is a public Codex skill and deterministic CLI for three related jobs:

- fetch a known paper from its DOI or official publisher page;
- build an auditable corpus for specified venues, years, topics, and quotas;
- prepare and carry out literature research for nearest work, claim evidence, Related Work, or gap analysis.

A completed acquisition is an identity-verified pair: the official publisher PDF and the publisher's raw BibTeX export. Crossref, OpenAlex, and Semantic Scholar can discover and enrich candidates, but they never replace those official artifacts. The project does not use mirrors, generate citations with an LLM, or bypass publisher access controls.

## Choose the workflow

| Your task | Workflow | What you get |
| --- | --- | --- |
| You have a DOI or official URL | `fetch` | One verified PDF/BibTeX pair, or an actionable access result |
| You need papers from specified venues, years, and topics | `discover corpus` → Codex review → `review corpus` → `acquire corpus` | Coverage evidence, a frozen selection, verified deliveries, and manual/retry queues |
| A publisher requires authorized user interaction | `manual-fetch` | The official files you download are taken over locally, identified, verified, and placed in the reserved delivery paths |
| You need nearest work, claim citations, Related Work, or a gap check | `discover research` followed by Codex review and full-text evidence work | A search plan and candidate package first; defensible evidence only after the closest papers are read |
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

Codex is part of the workflow. The CLI validates, checkpoints, freezes, and acquires deterministic artifacts; Codex translates the user's request into a specification and makes the recorded semantic review decisions.

## Install

The public discovery and non-browser workflows require Git, [uv](https://docs.astral.sh/uv/), and Python 3.11+. IEEE browser automation additionally requires Node.js, Windows PowerShell, and the pinned Playwright runtime. The current secure credential integration uses Windows DPAPI.

```powershell
$skill = Join-Path $env:USERPROFILE ".codex\skills\acquire-research-papers"
git clone https://github.com/EnosElinsa/acquire-research-papers.git $skill
uv sync --project $skill --locked --all-groups
& "$skill\scripts\install-playwright.ps1"
uv run --project $skill arp --help
```

For an existing installation:

```powershell
git -C $skill pull --ff-only
uv sync --project $skill --locked --all-groups
```

Delivery directories must be outside this repository. Runtime registries, encrypted secrets, caches, and dedicated browser profiles live under `%LOCALAPPDATA%\Codex`.

## First use: configure only what this task needs

Start by asking which optional capabilities are already configured:

```powershell
uv run --project $skill arp config status
```

The command returns booleans only. It checks the stored object shape without printing or decrypting any value. A `true` result means a local configuration exists; it does not prove live API or publisher entitlement. The agent should guide configuration only for a capability required by the current task, then test that capability with a representative operation.

| Capability | Configure it when | Setup |
| --- | --- | --- |
| None | Public Crossref discovery, ACL discovery/acquisition, or IJCAI discovery/acquisition | No secret setup |
| Semantic Scholar | You want keyed candidate search, higher limits, and the first DOI abstract-enrichment pass | `& "$skill\scripts\setup-discovery-api-keys.ps1" -Provider semantic_scholar` |
| OpenAlex | You want additional candidate search and a second DOI abstract-enrichment pass | `& "$skill\scripts\setup-discovery-api-keys.ps1" -Provider openalex` |
| IEEE | You want automatic access to subscribed IEEE PDFs through your institution and CARSI | `& "$skill\scripts\setup-ieee-institution.ps1"` |
| Elsevier | You need official metadata resolution for the manual ScienceDirect handoff | `& "$skill\scripts\setup-discovery-api-keys.ps1" -Provider elsevier` |
| MinerU | You need selected PDFs parsed for internal full-text analysis or explicit Markdown export | `& "$skill\scripts\setup-mineru-token.ps1"` |

All setup prompts are interactive and non-echoing. Never paste a password, API key, token, or cookie into chat, an agent message, a command argument, `.env`, or a repository file. Provider updates are independent: adding an OpenAlex key does not replace IEEE, MinerU, Elsevier, or Semantic Scholar configuration.

## Quick start

### Fetch one known paper

```powershell
uv run --project $skill arp fetch `
  --input "https://aclanthology.org/2024.acl-long.1/" `
  --output "C:\Research\papers"
```

Use the output only when the JSON status is `delivered`. A title alone must first be resolved through discovery; the fetch command will not guess between similarly named papers.

### Build a topic corpus

A user normally describes the task in plain language and lets Codex create the corpus specification. This compact example shows what is made explicit:

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
uv run --project $skill arp discover corpus --progress `
  --spec .\corpus.yaml --output C:\Research\corpus-run
```

Codex then reads `evidence-packets.jsonl`, reviews title and abstract evidence, and writes hash-bound decisions. Import those decisions and freeze the selection:

```powershell
uv run --project $skill arp review corpus `
  --run C:\Research\corpus-run `
  --decisions C:\Research\corpus-run\review-decisions.jsonl
```

Acquire only the frozen selection:

```powershell
uv run --project $skill arp acquire corpus `
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
scope:
  years: [2023, 2024, 2025, 2026]
delivery:
  write_narrative: false
  export_markdown: false
```

```powershell
uv run --project $skill arp discover research `
  --brief .\research-brief.yaml --output C:\Research\literature-review
```

This command currently returns `status: planned`: it prepares the four search passes and candidate package. It is not a claim that citation expansion, full-text reading, or gap validation is complete.

## How corpus discovery actually works

Corpus discovery is designed for bounded requests such as “papers from these venues, during these years, about these topics.” It uses the following process:

1. **Define the boundary.** Codex records exact venues, years, publication types, topics, exclusions, totals, and quotas.
2. **Enumerate before filtering.** ACL and IJCAI use official proceedings. Journals and identified conference collections use Crossref pagination by ISSN, collection DOI, venue, and year. OpenAlex and Semantic Scholar can add query-based candidates.
3. **Record coverage.** Every venue/year slice is marked complete, partial, or failed. A missing proceedings page or identifier becomes a diagnostic, not an empty result silently treated as complete.
4. **Merge and enrich.** Records are deduplicated primarily by DOI. Missing abstracts are looked up by DOI through Semantic Scholar and, when configured, OpenAlex. Field provenance remains attached to the candidate.
5. **Screen with evidence.** Deterministic rules reject wrong years, venues, tracks, types, and recognizable front matter. Keywords help nominate candidates, but acceptance requires Codex to judge both title and abstract and record a reason.
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

The current implementation is a foundation, not a one-command systematic review. The default `discover research` command:

- builds all four query forms;
- searches Crossref and deduplicates a bounded candidate set;
- writes the plan, candidate manifest, pending-review list, nearest-work matrix, evidence-map scaffold, and gap-report scaffold;
- deliberately asserts no novelty conclusion before full-text validation.

It does **not yet** execute the planned citation graph, use OpenAlex/Semantic Scholar as default research searchers, acquire and read the closest papers automatically, or populate claim-level evidence by itself. In the full Codex skill workflow, the agent must continue with publisher acquisition, optional MinerU parsing, manual evidence review, and bounded synthesis. The README treats these as remaining work instead of presenting empty scaffolds as completed research.

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

| Source | Discovery | PDF/BibTeX acquisition | Current maturity and fallback |
| --- | --- | --- | --- |
| Crossref | Primary venue/year enumeration and research search | No | Stable public metadata source; metadata completeness still varies by publisher |
| ACL Anthology | Official proceedings enumeration | Automatic | Mature and used in real corpus runs |
| IJCAI proceedings | Official proceedings and track parsing | Automatic | Mature and used in real corpus runs |
| IEEE Xplore | Candidates usually come from Crossref/OpenAlex/Semantic Scholar | Automatic with a configured CARSI institution profile | Generic profile-driven flow; live-tested end to end with one CARSI institution. Every additional institution requires first-use adaptation and a representative smoke test |
| ACM Digital Library | Usually Crossref collection enumeration plus optional query APIs | Conditional HTTP adapter | Works only when the official page and artifact endpoints allow the dedicated client. No production browser-backed ACM adapter exists yet; blocked pages become manual work |
| ScienceDirect | Crossref/OpenAlex/Semantic Scholar discovery; Elsevier API can resolve expected identity | Manual only | The user downloads in a normal authorized browser; the CLI verifies and imports the local pair. No scripted ScienceDirect login or browser automation |
| Semantic Scholar | Optional keyed candidate search; DOI abstract enrichment can use lower unauthenticated limits | No | Discovery evidence only |
| OpenAlex | Optional candidate search and DOI abstract enrichment | No | Discovery evidence only |
| MinerU | No | No | Optional seven-day full-text parsing cache; it is analysis support, not a paper source |
| Generic direct publisher adapter | Internal host-bounded adapter exists | Not enabled as a public production default | Requires an explicit approved-host configuration and productized setup before it should be advertised as general support |

## IEEE institutional access

IEEE uses a dedicated visible Chrome profile because authenticated access and PDF requests must share one isolated browser context. The workflow first tries the paper without reading credentials. If entitlement is missing, it:

1. enters the institution profile's exact CARSI IEEE resource gateway;
2. selects the exact configured institution option and writes and verifies its IdP entity ID;
3. releases the DPAPI-protected credential only on the exact configured IdP hostname and submits it at most once;
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
& "$skill\scripts\setup-discovery-api-keys.ps1" -Provider elsevier
```

Start the watcher before downloading:

```powershell
uv run --project $skill arp manual-fetch `
  --input "10.1016/j.asieco.2024.101746" `
  --watch "$HOME\Downloads" --output C:\Research\papers
```

The CLI opens only the canonical article page. The user completes organization login and downloads the official PDF plus raw BibTeX in a normal browser. The CLI observes only stable new or changed files, verifies the pair, and delivers it. It never controls ScienceDirect, reads the user's Chrome profile, exports cookies, or turns an Article Retrieval API 403 into scripted website login.

If both files already exist:

```powershell
uv run --project $skill arp manual-fetch --input <DOI> `
  --pdf .\paper.pdf --bibtex .\citation.bib --output C:\Research\papers
```

For a frozen corpus item, use its immutable selection ID:

```powershell
uv run --project $skill arp manual-fetch `
  --selection C:\Research\corpus-run\selection-manifest.json `
  --key <selection-id> --output C:\Research\corpus-delivery `
  --watch "$HOME\Downloads"
```

## Understand the outputs

| File | Meaning |
| --- | --- |
| `coverage.jsonl` | Which provider covered each requested venue/year slice and whether it was complete |
| `candidates.jsonl` | Deduplicated discovery ledger; not a final bibliography |
| `evidence-packets.jsonl` | Immutable title/abstract evidence Codex reviews |
| `pending-metadata.csv` | Candidates blocked by missing evidence such as an abstract |
| `pending-review.csv` | Review-ready candidates that still lack a semantic decision |
| `selected-papers.jsonl` | The frozen papers eligible for acquisition |
| `selection-manifest.json` | Hash binding for the normalized request and selected list |
| `acquisition-manifest.jsonl` | One durable delivery state per selected paper |
| `manual-download.csv` | Frozen selections needing authorized user action or a not-yet-supported safe adapter |
| `retryable-downloads.csv` | Transient failures that can be retried without changing the selection |
| `delivery-manifest.json` | Acquisition totals, selection binding, and completion state |

Use repeatable `--defer-host <exact-hostname>` options when a publisher must not be contacted in the current run. Deferred records remain in the selection and enter the manual queue; verified prior deliveries remain delivered.

## Accuracy and trust boundaries

The project improves reliability in three different ways:

- **Coverage accountability:** venue/year enumeration and a coverage ledger are stronger than trusting the first page of keyword results. They still cannot guarantee that upstream indexes contain every paper.
- **Relevance accountability:** deterministic hard gates and prefiltering reduce noise, but an accepted paper requires a recorded Codex judgment over title and abstract. This is more auditable than keyword-only acceptance, not a proof of universal semantic accuracy.
- **Artifact identity:** official-host boundaries, raw publisher BibTeX, metadata comparison, provenance, and hashes give the strongest guarantee in the system: the delivered files correspond to the frozen paper.

The repository has regression tests for its contracts and has completed real multi-venue corpus runs. It does not yet have a large, independently labeled cross-domain benchmark, so it must not advertise a measured precision/recall score. Missing abstracts, incomplete current-year indexes, ambiguous records, and boundary relevance judgments are reported rather than guessed.

## Current limitations

- The full IEEE/CARSI path has been live-validated with one CARSI institution. Every additional institution is profile-driven but still requires first-use observation and adaptation.
- Secure institutional credentials and the current guided setup are Windows/PowerShell/DPAPI oriented.
- IEEE journal discovery relies primarily on Crossref and optional metadata APIs; there is no official IEEE venue enumerator in the current release.
- ACM automation has no browser-backed production adapter. Official pages that block the HTTP client become manual items.
- ScienceDirect acquisition is manual only; the project intentionally does not automate organization login or the article page.
- `discover research` currently plans and scaffolds a review. Citation-graph execution, automatic closest-paper acquisition, and claim-level full-text evidence are not one-command features.
- A paper without a trustworthy abstract remains `pending_abstract`; title-only acceptance is forbidden.
- New or not-yet-published proceedings and inconsistent upstream metadata can leave coverage incomplete.
- `arp config status: true` confirms stored configuration shape, not live credentials, quota, subscription, or API entitlement.
- Large authenticated batches run conservatively and may be slow.
- Acquisition expects a clean or already bound delivery root; importing an existing hand-curated folder is not yet a first-class command.
- The internal generic publisher adapter is not a public plug-in system yet.
- No cross-domain labeled benchmark currently supports a numeric precision/recall claim.

## Roadmap

These are improvement priorities, not claims about current support.

### Near term

1. **Make research mode executable end to end.** Add OpenAlex and Semantic Scholar research searchers, real backward/forward citation traversal, closest-paper acquisition, resumable full-text review, and validated claim-level evidence import.
2. **Add an IEEE institution doctor.** Probe non-secret profile fields, show sanitized stage transitions, validate the resource gateway/entity ID/form contract, and run one representative smoke test without exposing credentials.
3. **Productize ACM authorized access.** Design a dedicated visible, isolated, exact-host browser contract with the same fail-closed standards as IEEE; retain manual fallback when access or page shape is unknown.
4. **Support safe delta acquisition and existing-folder import.** Bind a new frozen selection without colliding with already verified user files, and provide an explicit migration command instead of ad hoc copying.
5. **Publish copyable templates.** Add `arp init corpus` and `arp init research`, example specifications, and a human-readable run summary.

### Medium term

6. **Measure discovery quality.** Build labeled venue/topic fixtures and report coverage, precision, recall, pending-abstract rate, and reviewer disagreement by source and discipline.
7. **Expand official enumeration.** Add exact, auditable venue adapters where an official index or API exists, especially for IEEE and ACM collections, without weakening identifier requirements.
8. **Improve batch operations.** Add safe publisher-aware concurrency, progress snapshots, retry scheduling, and manual-queue batch handoff while preserving rate limits and shared-session safety.
9. **Improve portability.** Abstract the secret store behind operating-system keychains while keeping Windows DPAPI compatibility and never falling back to plaintext files.
10. **Open a publisher plug-in contract.** Let users register exact approved hosts and tested page contracts for the generic adapter without accepting arbitrary redirects or generated citations.

ScienceDirect browser automation is deliberately not on the roadmap unless publisher policy and a safe official integration make it appropriate.

## Optional Markdown policy

Research work may parse a selected PDF through a seven-day SHA-256 MinerU cache for internal reading. Ordinary fetch, manual fetch, corpus discovery, review, and acquisition produce no Markdown. Export only after the user explicitly requests a destination:

```powershell
uv run --project $skill arp export-md `
  --pdf .\paper.pdf --output C:\Research\markdown
```

## Development

```powershell
uv sync --locked --all-groups
uv run ruff check src tests scripts/validate_skill.py
uv run pytest -q
uv run python scripts/validate_skill.py .
node --test tests/node/test-ieee-playwright.mjs
./tests/powershell/test-secret-store.ps1
./tests/powershell/test-install-playwright.ps1
```

See [references/corpus-mode.md](references/corpus-mode.md), [references/research-mode.md](references/research-mode.md), [references/source-policies.md](references/source-policies.md), [references/credentials-and-cache.md](references/credentials-and-cache.md), and [SECURITY.md](SECURITY.md) for the normative contracts.

## Responsible use

Use institutional access only within the account and license terms that authorize the requested material. The project does not bypass publisher controls, redistribute acquired papers, automate prohibited publisher interactions, or weaken an institution's authentication flow.

Licensed under the [MIT License](LICENSE).
