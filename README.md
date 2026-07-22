# Acquire Research Papers

[简体中文](README.zh-CN.md)

[![CI](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml/badge.svg)](https://github.com/EnosElinsa/acquire-research-papers/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A global Codex skill and deterministic CLI for discovering and acquiring research papers. Every completed acquisition contains a publisher-hosted PDF, the publisher's raw BibTeX export, and provenance tying both artifacts to the same work.

Discovery APIs may propose candidates, but they never replace official artifacts. Ambiguous and boundary papers go to a review queue instead of being silently accepted.

## Workflows

| Workflow | Use it for | Result |
| --- | --- | --- |
| `fetch` | DOI, official URL, or explicit paper list | Verified PDF and raw BibTeX pair |
| `manual-fetch` | Authorized browser download requiring user interaction | Automatic local takeover, verification, and delivery |
| `discover corpus` | Venue, topic, year, and count constraints | Coverage ledger plus immutable evidence packets |
| `review corpus` | Codex semantic decisions over discovery evidence | Validated, quota-aware frozen selection |
| `acquire corpus` | A frozen corpus selection | Verified pairs plus separate manual and retry queues |
| `discover research` | Gap analysis, similar work, claim evidence, or Related Work | Evidence maps, comparisons, gaps, and review records |

PDF-to-Markdown is optional. Research mode may temporarily parse selected PDFs with MinerU for evidence analysis; Markdown is exported only on explicit request.

## Supported sources

- ACL Anthology and IJCAI proceedings
- IEEE Xplore, including an optional user-configured CARSI institutional profile
- ACM Digital Library
- ScienceDirect through a manual organization-login handoff
- Direct publisher pages exposing one unambiguous PDF and raw BibTeX link

Crossref, OpenAlex, and Semantic Scholar are discovery sources only. Mirrors, generated citations, and metadata-only records do not satisfy delivery.

## Install globally

Prerequisites are Git, [uv](https://docs.astral.sh/uv/), and Python 3.11+. Node.js and the pinned Playwright runtime are needed only for browser-backed adapters such as IEEE. Windows DPAPI protects institutional credentials and optional API keys.

```powershell
$skill = Join-Path $env:USERPROFILE ".codex\skills\acquire-research-papers"
git clone https://github.com/EnosElinsa/acquire-research-papers.git $skill
uv sync --project $skill --locked --all-groups
& "$skill\scripts\install-playwright.ps1"
uv run --project $skill arp --help
```

For an existing installation, run `git pull --ff-only`, then repeat `uv sync --locked --all-groups`.

## Usage

Fetch a directly supported paper:

```powershell
uv run --project $skill arp fetch `
  --input "https://aclanthology.org/2024.acl-long.1/" `
  --output "C:\Research\papers"
```

For subscribed ScienceDirect content, start the watcher before downloading:

```powershell
uv run --project $skill arp manual-fetch `
  --input "10.1016/j.asieco.2024.101746" `
  --watch "$HOME\Downloads" `
  --output "C:\Research\papers"
```

The CLI opens the canonical publisher page. You complete organization login and manually download the PDF plus the publisher's raw BibTeX. The CLI observes only new or changed stable files, verifies DOI/title/year/venue/first author and PDF identity, then delivers them with `manual_publisher_download` provenance. It does not automate ScienceDirect, inspect your normal Chrome profile, or read/export Cookie data.

If the files were already downloaded:

```powershell
uv run --project $skill arp manual-fetch --input <DOI> `
  --pdf .\paper.pdf --bibtex .\citation.bib --output C:\Research\papers
```

Corpus discovery, corpus acquisition, research, and optional Markdown export:

```powershell
uv run --project $skill arp discover corpus `
  --spec .\corpus.yaml --output C:\Research\corpus-discovery
uv run --project $skill arp review corpus `
  --run C:\Research\corpus-discovery `
  --decisions C:\Research\review-decisions.jsonl
uv run --project $skill arp acquire corpus `
  --selection C:\Research\corpus-discovery\selection-manifest.json `
  --output C:\Research\corpus `
  --defer-host publisher.example
uv run --project $skill arp discover research --brief .\brief.yaml --output C:\Research\review
uv run --project $skill arp export-md --pdf .\paper.pdf --output C:\Research\markdown
```

Discovery paginates venue/year sources and writes `coverage.jsonl`, `candidates.jsonl`, `evidence-packets.jsonl`, `pending-metadata.csv`, and `discovery-manifest.json`; it performs no publisher download and does not freeze a selection. Codex reviews title and abstract evidence, while keywords are optional and full text is not required. `review corpus` validates `review-decisions.jsonl` against immutable evidence hashes, applies quotas, and writes `selected-papers.jsonl` plus `selection-manifest.json`. Acquisition consumes only that frozen selection and never adds or removes papers. It writes verified pairs, `acquisition-manifest.jsonl`, `manual-download.csv`, `retryable-downloads.csv`, and `delivery-manifest.json`.

Acquisition does not stop when one selected paper needs user access. It finishes the remaining selections and writes the inaccessible item to `manual-download.csv` with its frozen selection ID, DOI, official URL, publisher host, reason, and reserved target paths. Complete it with `manual-fetch --selection <manifest> --key <selection-id>` so the local files are verified against the frozen identity before delivery.

Repeat `--defer-host <exact-hostname>` to prevent selected publisher hosts from being contacted in a run. Existing hash-verified deliveries are reused; other matching records remain in the frozen selection and are written to the manual queue.

Delivery directories must remain outside this repository. Runtime state is stored under `%LOCALAPPDATA%\Codex`.

## Credentials and API keys

This repository contains no accounts, passwords, API keys, tokens, cookies, or browser profiles.

Configure your own IEEE institution profile and credential from an interactive PowerShell terminal:

```powershell
& "$skill\scripts\setup-ieee-institution.ps1"
```

The profile includes the exact post-login CARSI IEEE resource URL. Attribute release is never accepted by default; pass `--accept-ieee-attribute-release` to `fetch` or `acquire corpus` only when you explicitly authorize the configured accept control. The reject control is never clicked, and PDF retrieval starts only after the persistent browser context returns to `ieeexplore.ieee.org`.

Configure MinerU independently only when Markdown extraction is needed:

```powershell
& "$skill\scripts\setup-mineru-token.ps1"
```

Configure the Elsevier API key used only for official metadata resolution:

```powershell
& "$skill\scripts\setup-elsevier-api-key.ps1"
```

The setup asks for the institution's exact CARSI option, exact identity-provider hostname, accessible form labels, resource gateway, and optional exact attribute-release controls; the repository supplies no school-specific defaults. Credential prompts do not echo values, and DPAPI ties the encrypted payload to the current Windows user. The manual ScienceDirect workflow stores no institution password. An Elsevier Article Retrieval entitlement is not assumed; a 403 falls back to the user-driven browser download rather than website automation.

See [`references/credentials-and-cache.md`](references/credentials-and-cache.md) and [`SECURITY.md`](SECURITY.md).

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

## Responsible use

Use institutional access only within the account and license terms that authorize the requested material. The project does not bypass publisher controls, redistribute acquired papers, automate prohibited publisher interactions, or weaken an institution's authentication flow.

Licensed under the [MIT License](LICENSE).
