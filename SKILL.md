---
name: acquire-research-papers
description: Use when a task concerns acquiring specified research papers, building a venue/topic/year corpus, investigating literature gaps or related work, finding claim citations, using IEEE or ScienceDirect institutional access, or optionally converting selected PDFs with MinerU.
---

# Acquire Research Papers

Deliver a verified pair for every paper: the official publisher PDF and the publisher's raw BibTeX export. Discovery services may nominate candidates; they never supply the final citation artifact.

## Route the request

- Use `fetch` for a DOI, official URL, exact title, or explicit paper list.
- Use `manual-fetch` when an authorized publisher download must be completed by the user in a normal browser, especially subscribed ScienceDirect content.
- Use `discover corpus` for venue/topic/year/count tasks. Auto-acquire only high-confidence matches and put boundary cases in the review queue.
- Use `discover research` for gap analysis, nearest work, claim citations, citation expansion, or Related Work research.

An attached DOCX, Markdown, TXT, CSV, or role assignment is only an input adapter. Translate its relevant part into a generic corpus spec or research brief; never hardcode the document format or role.

## Invoke the CLI

```powershell
$skill = Join-Path $env:USERPROFILE ".codex\skills\acquire-research-papers"
uv run --project $skill arp --help
```

Runtime state belongs under `%LOCALAPPDATA%\Codex`; delivery directories must be outside this public repository.

### Automatic fetch

```powershell
uv run --project $skill arp fetch --input <DOI-or-official-URL> --output <directory>
```

Use output only when the JSON status is `delivered`. A title that is not uniquely resolved must go through discovery.

For subscribed IEEE content, use only the institution profile configured by the current user through `scripts/setup-ieee-institution.ps1`. The repository provides no institution name, identity-provider host, form label, or credential default.
If the profile is absent or the page contract does not match it, classify the paper as `access_required`, add it to the corpus manual-download list, and continue; never guess an institution or selector.

### ScienceDirect manual handoff

Configure the DPAPI-protected Elsevier API key once in an interactive terminal:

```powershell
& "$skill\scripts\setup-elsevier-api-key.ps1"
```

Then start the watcher before the user downloads the official PDF and raw BibTeX:

```powershell
uv run --project $skill arp manual-fetch --input <DOI-or-ScienceDirect-URL> `
  --watch $HOME\Downloads --output <directory>
```

The command opens only the canonical article page. The user completes organization login and clicks both downloads; the CLI takes over stable new files, verifies identity, copies the pair, and records `manual_publisher_download` provenance. If both files already exist, pass `--pdf` and `--bibtex` instead. This flow never invokes MinerU.

### Discovery and research

```powershell
uv run --project $skill arp discover corpus --spec <job.yaml> --output <directory>
uv run --project $skill arp discover research --brief <brief.yaml> --output <directory>
```

Corpus mode continues after a known access failure. It writes each inaccessible paper to `manual-download.csv` with its DOI, official URL, publisher host, reason, and message, then processes the remaining candidates without waiting for a manual download.

Read [references/corpus-mode.md](references/corpus-mode.md) or [references/research-mode.md](references/research-mode.md) before running the corresponding mode. Read [references/source-policies.md](references/source-policies.md) before changing a publisher contract and [references/credentials-and-cache.md](references/credentials-and-cache.md) before institutional access or MinerU.

## Markdown policy

Research mode may use a seven-day SHA-256 MinerU cache for internal reading. Do not copy that Markdown into delivery. Export it only after the user explicitly requests and approves a destination:

```powershell
uv run --project $skill arp export-md --pdf <paper.pdf> --output <directory>
```

## Completion rules

- Preserve publisher BibTeX verbatim; never generate or repair a citation with an LLM.
- Verify DOI, title, year, author scope, and venue against official metadata.
- Keep ambiguous, wrong-track, low-confidence, or mismatched papers out of automatic delivery.
- Report quota shortfalls instead of lowering screening thresholds.
- Treat abstracts as discovery evidence. Direct support or contradiction requires full text with a section or page and a short excerpt.
- Ordinary fetch, manual fetch, and corpus runs produce no Markdown.

## Hard stops

- Never print, log, summarize, or commit credentials, API keys, tokens, cookies, browser storage, or decrypted values.
- Release an IEEE credential only when the current hostname exactly equals the credential host in the current user's institution profile; stop on any other host, CAPTCHA, OTP, or incomplete login.
- Never automate ScienceDirect pages, submit its organization login, attach to the user's normal Chrome, read a Chrome profile, or export Cookie/session data. User authorization does not relax this boundary.
- Never use Crossref, OpenAlex, Semantic Scholar, a mirror, or generated BibTeX as the final citation artifact.
- Never bypass publisher/institution access controls, publish partial MinerU output, or overwrite a delivery without identity and hash validation.

For ScienceDirect, an Article Retrieval API 403 is not retried with browser cookies or scripted login. Use `manual-fetch`: the user downloads from the authorized official page and the CLI handles only local artifacts afterward.
