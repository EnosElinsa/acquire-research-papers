---
name: acquire-research-papers
description: Acquire official research-paper PDF/BibTeX pairs; discover venue/topic corpora or an author's publications; audit, update, import, and organize local paper libraries; configure named IEEE institution access; or investigate literature evidence and gaps.
---

# Acquire Research Papers

Deliver the official publisher PDF and the publisher's raw BibTeX export as a verified pair. Discovery metadata nominates candidates and supports comparison; it never becomes the final citation artifact.

## Run the installed skill

Resolve this skill's actual installed directory, then run its portable launcher:

```text
python <skill-directory>/scripts/arp.py --help
python <skill-directory>/scripts/arp.py config status
```

Python 3.11+ and `uv` are required. The standard-library launcher installs the fixed release wheel from `runtime.json` only after verifying SHA-256, in a separate cache outside the skill. No developer checkout or project environment is needed. A release wheel that has not yet been published cannot bootstrap from its release URL; a matching local release wheel may be supplied through `ARP_LOCAL_WHEEL` for isolated validation.

Check `arp config status` first. IEEE, MinerU, Elsevier, Semantic Scholar, and OpenAlex are optional and independent; configure only the capability needed for the current task. Select the user's named institution profile for IEEE access. Stored configuration and historical checks do not prove current subscription or API entitlement. Never request secrets in chat. Public schema snapshots are included for reference; `arp schema <schema-name.json>` returns the authoritative schema bundled with the running release.

## Route the task

| Request | Command and reference |
| --- | --- |
| Configure an institution, switch profiles, log in, or validate access | `arp config setup ieee`, `arp config ieee list/use/login/doctor`; read [configuration](references/configuration.md) |
| Configure one API/parser provider | `arp config setup <provider>`; read [credentials and cache](references/credentials-and-cache.md) |
| Known DOI, publisher URL, exact title, or explicit paper list | `arp fetch`; read [acquisition workflows](references/workflows.md) |
| User-operated ScienceDirect download | `arp manual-fetch`; read [source policies](references/source-policies.md) |
| Existing library consistency, publication changes, missing pairs, or duplicates | `arp library audit/update`; read [library mode](references/library-mode.md) |
| Import, rename, organize, or extract explicitly identified book chapters | `arp library import/organize/apply`; read [library mode](references/library-mode.md) |
| Publications by an author, including a date range or local-library comparison | `arp discover author`; read [author mode](references/author-mode.md) |
| Venue/topic/year/count corpus | `arp discover corpus --progress` → `arp review corpus` → `arp acquire corpus`; read [corpus mode](references/corpus-mode.md) |
| Nearest work, Related Work, claim citations, or gap evidence | `arp discover research` → review → acquire → evidence; read [research mode](references/research-mode.md) |
| Explicit PDF-to-Markdown export | `arp export-md`; read [credentials and cache](references/credentials-and-cache.md) |

An attached document or role assignment is an input adapter: translate its relevant requirements into the generic corpus/research/author specification. Keep corpus and research frozen hashes unchanged when running a library or author task.

## Review and completion

- Preserve original BibTeX bytes, BOM, encoding, and line endings. Decode only a parsing view. Never generate or repair citations with an LLM or a metadata API.
- Verify DOI, title, year, author scope, and venue. Report ambiguous identities and partial evidence explicitly.
- Corpus decisions inspect `evidence-packets.jsonl` and record title-and-abstract evidence. Acquire only the frozen `selected-papers.jsonl` bound by `selection-manifest.json`; keywords are optional and full text is not required for corpus relevance.
- `--defer-host` retains selections in `manual-download.csv`; never remove difficult papers from a frozen selection or lower relevance thresholds to fill a quota.
- Library audits distinguish the local PDF version, citation placement, and current metadata. A current citation does not prove the PDF is current. Review `plan.json` before explicit `arp library apply --plan <path>`; update/import/organize do not apply automatically. Retain backups for rollback.
- Author discovery reports source coverage, identity ambiguity, formal/early-access/preprint groups, and separate issue/online dates. Never claim an absolutely complete bibliography.
- Ordinary fetch, manual fetch, and corpus workflows produce no Markdown. Research uses an internal MinerU cache; export Markdown only after an explicit user destination request.

## Access boundaries

Read [source policies](references/source-policies.md) before changing an acquisition contract and [configuration](references/configuration.md) before institution adaptation.

Never print, log, commit, or send credentials, tokens, cookies, browser storage, or decrypted values. Keep state and deliveries outside the public repository. IEEE uses an isolated visible profile for the selected institution; credentials are released only at its exact configured hostname. A successful identity-provider login is separate from return to IEEE, a verified download, and proof of institutional entitlement.

Never automate ScienceDirect article pages or ScienceDirect organization-login flows, attach to the user's normal Chrome, read its profile, or export Cookie/session data. Authorized users download PDF and raw BibTeX themselves; the CLI handles local stable files afterward. Do not bypass publisher/institution controls or substitute mirrors, discovery BibTeX, or generated citations.
