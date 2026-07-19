---
name: acquire-research-papers
description: Discover, verify, and acquire research papers with their official publisher BibTeX. Use when a user asks to fetch specified papers, assemble a venue/topic/year corpus, investigate literature gaps or related work, find claim-supporting citations, use IEEE institutional access, or optionally convert selected PDFs to Markdown with MinerU.
---

# Acquire Research Papers

Deliver a verified pair for every paper: the official publisher PDF and the publisher's raw BibTeX export. Discovery services may nominate candidates; they never supply the final citation artifact.

## Route the request

- Use `fetch` when the user supplies a DOI, publisher URL, exact title, or explicit paper list.
- Use `discover corpus` for venue/topic/year/count tasks. Auto-acquire only high-confidence matches and place boundary cases in the review queue.
- Use `discover research` for gap analysis, nearest work, claim citations, citation expansion, or Related Work research.

An attached DOCX, Markdown, TXT, CSV, or role assignment is an optional input adapter. Convert its relevant portion into a generic corpus spec or research brief; never hardcode the document format or role into the workflow.

## Invoke the deterministic CLI

Resolve the installed skill directory first so commands work from any project:

```powershell
$skill = Join-Path $env:USERPROFILE ".codex\skills\acquire-research-papers"
uv run --project $skill arp --help
```

All runtime state belongs under `%LOCALAPPDATA%\Codex`; delivery directories must be outside this public skill repository.

### Fetch

```powershell
uv run --project $skill arp fetch --input <DOI-or-official-URL> --output <directory>
```

Use the emitted JSON only after `status` is `delivered`. A title that is not uniquely resolved must go through discovery first.

Read [references/source-policies.md](references/source-policies.md) before using a new publisher or repairing a page contract. Read [references/credentials-and-cache.md](references/credentials-and-cache.md) before institutional access or MinerU.

### Discover a corpus

Translate the request into `schemas/corpus-spec.schema.json`, then run:

```powershell
uv run --project $skill arp discover corpus --spec <job.yaml> --output <directory>
```

Read [references/corpus-mode.md](references/corpus-mode.md) for screening, quotas, acquisition, review, and task-file adaptation.

### Research a question

Translate the question into `schemas/research-brief.schema.json`, then run:

```powershell
uv run --project $skill arp discover research --brief <brief.yaml> --output <directory>
```

Read [references/research-mode.md](references/research-mode.md) before searching, parsing full text, or recording evidence.

## Markdown policy

PDF-to-Markdown is optional. Research mode may use a seven-day, SHA-256-addressed MinerU cache for internal reading. Do not copy that Markdown into the user's output. Export Markdown only when the user explicitly requests it and names or approves a destination.

```powershell
uv run --project $skill arp export-md --pdf <paper.pdf> --output <directory>
```

## Completion rules

- Preserve the publisher's raw BibTeX response; never generate or repair a citation with an LLM.
- Verify DOI, title, year, author list, and venue between publisher metadata and BibTeX.
- Keep low-confidence, wrong-track, ambiguous, or metadata-mismatched papers out of automatic delivery.
- Report a quota shortfall instead of lowering the screening threshold.
- Treat abstracts as discovery evidence. Direct support and contradiction require full-text reading with a section or page and a short excerpt.
- Ordinary fetch and corpus runs create no Markdown.

## Hard stops

- Never print, log, summarize, or commit credentials, tokens, cookies, browser storage, or decrypted values.
- Release the Guangxi University credential only to exact host `idp.gxu.edu.cn`; stop on any other host, CAPTCHA, OTP, or incomplete login.
- Never attach automation to the user's normal Chrome profile or export cookies.
- Never bypass a publisher or institution access control.
- Never treat Crossref, OpenAlex, Semantic Scholar, a mirror, or a parsed PDF as the official BibTeX source.
- Never publish partial MinerU output or overwrite an existing delivery without identity and hash validation.

When a named page phase fails, inspect only that publisher page in the dedicated browser profile, update the narrow selector or contract and its fixture test, rerun the focused tests, then retry once.
