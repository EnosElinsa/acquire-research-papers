---
name: acquire-research-papers
description: Acquire official research-paper PDF/BibTeX pairs; discover venue/topic corpora or an author's publications; audit, update, import, and organize local paper libraries; configure named IEEE institution access; or investigate literature evidence and gaps.
---

# Acquire Research Papers

Deliver the official publisher PDF and the publisher's raw BibTeX export as a verified pair. Discovery metadata nominates candidates and supports comparison; it never becomes the final citation artifact.

## Run the installed skill

Use this shared skill in Codex, Claude Code, Kiro IDE, or Kiro CLI. Resolve its actual installed directory, then run its portable launcher through the selected host's shell tool:

```text
python <skill-directory>/scripts/arp.py --help
python <skill-directory>/scripts/arp.py doctor --host <actual-host> --skill-directory <skill-directory>
python <skill-directory>/scripts/arp.py config status
```

Python 3.11+ and `uv` are required. The standard-library launcher installs the fixed release wheel from `runtime.json` only after verifying SHA-256, in a separate cache outside the skill. No developer checkout or project environment is needed. A release wheel that has not yet been published cannot bootstrap from its release URL; a matching local release wheel may be supplied through `ARP_LOCAL_WHEEL` for isolated validation.

Read [host installation](references/hosts.md) for host paths, Kiro custom-agent resources, and checked support limits. The host doctor performs local checks by default; host loading, remote availability, and institutional access remain separate and unverified unless checked explicitly.

Check `arp config status` first. IEEE, MinerU, Elsevier, Semantic Scholar, and OpenAlex are optional and independent; configure only the capability needed for the current task. New installations use an editable local `.env` outside the repository: `arp config init`, `arp config path`, and `arp config edit`. A user may fill it locally or use non-echoing `config setup` prompts. Never ask for secret values in chat or command arguments. Legacy DPAPI installations remain legacy until explicit `arp config migrate --from dpapi` on the original Windows account. See [credentials and cache](references/credentials-and-cache.md).

Select the user's named institution profile for IEEE access. Stored configuration and historical checks do not prove current subscription or API entitlement. Public schema snapshots are included for reference; `arp schema <schema-name.json>` returns the authoritative schema bundled with the running release.

## Route the task

| Request | Command and reference |
| --- | --- |
| Known DOI, publisher URL, exact title, or explicit paper list | `arp fetch`; read [acquisition workflows](references/workflows.md) |
| Venue/topic/year/count corpus | `arp discover corpus --progress` → `arp review corpus` → `arp acquire corpus`; read [corpus mode](references/corpus-mode.md) |
| Nearest work, Related Work, claim citations, or gap evidence | `arp discover research` → review → acquire → evidence; read [research mode](references/research-mode.md) |

Start with [copyable recipes](examples/README.md). Related Work and gap analysis share one research workflow; choose the question type in the brief. Discovery writes state only. Evidence review produces `reports/report.md`; add `--export-csv` for tables. Never draft placeholder conclusions during discovery.

Advanced tasks: [author bibliographies](references/author-mode.md), [library audit/update/import/organize and explicit chapters](references/library-mode.md), [independent capabilities and run recovery](references/capabilities.md), [institution profiles](references/configuration.md), and [explicit Markdown export](references/credentials-and-cache.md). Read only the reference needed for the task. Author and library audit default to JSON plus `report.md`; CSV is opt-in.

Before planning venue coverage, use `arp sources --spec <corpus.yaml>` and read [sources and coverage](references/sources.md). This offline diagnostic describes capability, not live coverage or universal completeness. Translate attached documents into the same explicit inputs. Keep corpus and research frozen hashes unchanged when running library or author tasks.

## Review and completion

- Preserve original BibTeX bytes, BOM, encoding, and line endings. Decode only a parsing view. Never generate or repair citations with an LLM or a metadata API.
- Verify DOI, title, year, author scope, and venue. Report ambiguous identities and partial evidence explicitly.
- Corpus decisions inspect `evidence-packets.jsonl` and record title-and-abstract evidence. Acquire only the frozen `selected-papers.jsonl` bound by `selection-manifest.json`; keywords are optional and full text is not required for corpus relevance.
- The executing agent makes semantic decisions and records the actual host. New v2 decisions set `reviewer` and `executor.host` to that host; include model/version only when actually available. Preserve legacy Codex v1 review bytes and hashes. Never relabel another host as Codex or invent model metadata. Identity, relevance, and full-text evidence policies remain distinct.
- `--defer-host` retains selections in `manual-download.csv`; never remove difficult papers from a frozen selection or lower relevance thresholds to fill a quota.
- Library audits distinguish the local PDF version, citation placement, and current metadata. A current citation does not prove the PDF is current. Review `plan.json` before explicit `arp library apply --plan <path>`; update/import/organize do not apply automatically. Retain backups for rollback.
- Author discovery reports source coverage, identity ambiguity, formal/early-access/preprint groups, and separate issue/online dates. Never claim an absolutely complete bibliography.
- Ordinary fetch, manual fetch, and corpus workflows produce no Markdown. Research uses an internal MinerU cache; export Markdown only after an explicit user destination request.
- A standalone `parse --pdf` needs no BibTeX but retains user-supplied trust. It does not satisfy the official-pair delivery contract. Capability `export --format markdown` formats structured records; it is separate from `export-md` of full text.
- Capability runs record input/output hashes, item states, and next actions. Reuse the same `--run` and command inputs to resume; use `arp run status --run <directory>` to inspect them. A read-only adapter also summarizes supported legacy manifests without rewriting or converting them; legacy runs use their original resume commands. Agent review, user download, missing configuration, rate limits, retryable errors, and permanent failures remain distinct. Complete unrelated items without erasing blocked ones.

## Access boundaries

Read [source policies](references/source-policies.md) before changing an acquisition contract and [configuration](references/configuration.md) before institution adaptation.

Never print, log, commit, or send credentials, tokens, cookies, browser storage, or decrypted values. Keep state and deliveries outside the public repository. IEEE uses an isolated visible profile for the selected institution; credentials are released only at its exact configured hostname. A successful identity-provider login is separate from return to IEEE, a verified download, and proof of institutional entitlement.

Never automate ScienceDirect article pages or ScienceDirect organization-login flows, attach to the user's normal Chrome, read its profile, or export Cookie/session data. Authorized users download PDF and raw BibTeX themselves; the CLI handles local stable files afterward. Do not bypass publisher/institution controls or substitute mirrors, discovery BibTeX, or generated citations.
