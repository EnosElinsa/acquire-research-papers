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
| `discover corpus` | Venue, topic, year, and count constraints | High-confidence acquisitions plus a review queue |
| `discover research` | Gap analysis, similar work, claim evidence, or Related Work | Evidence maps, comparisons, gaps, and review records |

PDF-to-Markdown is optional. Research mode may temporarily parse selected PDFs with MinerU for evidence analysis; Markdown is exported only on explicit request.

## Supported sources

- ACL Anthology and IJCAI proceedings
- IEEE Xplore, including an optional Guangxi University institutional adapter
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

Corpus, research, and optional Markdown export:

```powershell
uv run --project $skill arp discover corpus --spec .\corpus.yaml --output C:\Research\corpus
uv run --project $skill arp discover research --brief .\brief.yaml --output C:\Research\review
uv run --project $skill arp export-md --pdf .\paper.pdf --output C:\Research\markdown
```

Delivery directories must remain outside this repository. Runtime state is stored under `%LOCALAPPDATA%\Codex`.

## Credentials and API keys

This repository contains no accounts, passwords, API keys, tokens, cookies, or browser profiles.

Configure IEEE/Guangxi University and MinerU from an interactive PowerShell terminal:

```powershell
& "$skill\scripts\setup-secrets.ps1"
```

Configure the Elsevier API key used only for official metadata resolution:

```powershell
& "$skill\scripts\setup-elsevier-api-key.ps1"
```

Prompts do not echo values. DPAPI ties the encrypted payload to the current Windows user. The manual ScienceDirect workflow does not store or release a South China Agricultural University password. An Elsevier Article Retrieval entitlement is not assumed; a 403 falls back to the user-driven browser download rather than website automation.

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
