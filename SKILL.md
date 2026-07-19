---
name: acquire-research-papers
description: Discover, verify, and acquire research papers with their official publisher BibTeX. Use when a user asks to fetch specified papers, assemble a venue/topic/year corpus, investigate literature gaps or related work, find claim-supporting citations, use IEEE institutional access, or optionally convert selected PDFs to Markdown with MinerU.
---

# Acquire Research Papers

Acquire a verified pair for every delivered paper: an official publisher PDF and the publisher's raw BibTeX export.

## Route the request

- Use `fetch` when the user supplies a DOI, publisher URL, title, or explicit list.
- Use `discover corpus` for venue/topic/year/count collection tasks. Auto-download only high-confidence matches and place boundary cases in the review queue.
- Use `discover research` for gap analysis, nearest work, claim evidence, citation expansion, or Related Work research.

Run `arp --help` for the deterministic command interface. Read the matching file under `references/` before executing a provider-specific or research workflow.

Markdown is optional. In research mode, temporary MinerU parsing may be used as a seven-day internal analysis cache. Export Markdown only when the user explicitly requests it.

Never invent BibTeX, treat discovery metadata as an official citation, expose credentials, or weaken a screening threshold merely to fill a quota.
