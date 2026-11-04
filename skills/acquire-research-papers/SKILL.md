---
name: acquire-research-papers
description: Acquire official research-paper PDF/BibTeX pairs; discover venue/topic corpora or an author's publications; audit, update, import, and organize local paper libraries; configure named IEEE institution access; or investigate literature evidence and gaps.
---

# Acquire Research Papers

Deliver the official publisher PDF and the publisher's raw BibTeX export as a verified pair. Discovery metadata nominates candidates and supports comparison; it never becomes the final citation artifact.

## Run the installed skill

`arp` below means `python <skill-directory>/scripts/arp.py`, where `<skill-directory>` is this skill's actual installed directory. Run it through the current host's shell tool; commands are single lines, so adapt only the quoting.

```text
arp doctor --host <actual-host> --skill-directory <skill-directory>
arp config status
```

Python 3.11+ and `uv` are required. The standard-library launcher installs the release wheel pinned in `runtime.json` after verifying its SHA-256, in a cache outside the skill; no source checkout is needed. A matching local release wheel may be supplied through `ARP_LOCAL_WHEEL` for isolated validation. See [host installation](references/hosts.md) for host paths and checked support limits.

IEEE, MinerU, Elsevier, Semantic Scholar, and OpenAlex are optional and independent; configure only the capability the current task needs, with `arp config setup <provider>` or by letting the user edit the file shown by `arp config path`. Never ask for secret values in chat or command arguments. Legacy DPAPI installations stay legacy until an explicit `arp config migrate --from dpapi`. See [credentials and cache](references/credentials-and-cache.md); for IEEE access, select the user's named institution profile and read [configuration](references/configuration.md). Stored configuration and historical checks do not prove current subscription or API entitlement.

## Route the task

| Request | Commands | Read |
| --- | --- | --- |
| Known DOI, publisher URL, or explicit paper list | `arp fetch` per paper; `arp manual-fetch` for a pair the user downloads | [acquisition workflows](references/workflows.md) |
| Venue/topic/year/count corpus | `arp discover corpus --progress` → agent review → `arp review corpus` → `arp acquire corpus` | [corpus mode](references/corpus-mode.md) |
| Nearest work, Related Work, claim citations, or gap evidence | `arp discover research` → `review research` → `acquire research` → `evidence research` | [research mode](references/research-mode.md) |
| An author's publications | `arp discover author` | [author mode](references/author-mode.md) |
| Local library audit, update, import, organize, or explicit chapters | `arp library …` | [library mode](references/library-mode.md) |
| One step on its own: resolve, enrich, freeze, verify, parse, export, run status | capability commands | [capabilities](references/capabilities.md) |

Start from the [copyable recipes](examples/README.md). Before planning venue coverage, run `arp sources --spec <corpus.yaml>` and read [sources and coverage](references/sources.md); it describes capability, not live coverage. Translate an attached document into a corpus spec or research brief. Read only the references the task needs. `arp schema <schema-name.json>` returns the authoritative schema of the running release; the bundled schema files are snapshots. Common IEEE journals and conferences (TMC, TWC, JSAC, IoT-J, INFOCOM, ICC, GLOBECOM, …), SIGCOMM, and AAAI are built-in venue presets: a venue named only by its short name receives checked identifiers, and `arp sources` lists them. Relay the `next_actions` of `discover corpus`: a missing API key that left abstracts pending, or a slice OpenAlex may not have indexed fully yet (`possible_upstream_lag`). Rerunning the same command into the same output looks up pending abstracts and warned slices again without refetching finished slices.

## Act on every result

Each command prints one JSON object on stdout. Batch ledgers record one state per paper. Handle every state; finish unrelated papers without erasing blocked ones.

| State (error codes) | Meaning | Next action |
| --- | --- | --- |
| `delivered` | Official PDF and raw BibTeX verified | Report the paths. |
| `manual_required` (`access_required`, `unsupported_adapter`) | Needs the user's authorized download, an institution login, or a publisher without an adapter (IEEE outside Windows) | The user downloads both files from the official pages; `manual-download.html` beside the queue lists every item with its official link. Import the whole queue in one session with `arp manual-fetch --selection <selection-manifest.json> --queue --output <delivery-root>`, add `--from <folder>` when the files are already downloaded, use `--key <selection-id>` for one item, or `--input <DOI>` for a single paper. A rerun of `acquire` does not request a paper whose access was refused again (`not_retried`); add `--retry-manual` after access changes. |
| `retryable` (`network_transient`, `rate_limited`, `automation_error`, `host_paused`) | Temporary failure, or the host was paused for the rest of the run | Rerun the same command with the same output later; verified papers are skipped. |
| `contract_error` (`contract_error`) | The official page or artifact broke its contract or identity check | Report the message. Do not retry blindly or substitute another source. |
| `contract_error` (`configuration_required`) | A local prerequisite such as the IEEE browser runtime is missing | Check `arp doctor`, configure only that capability, or use `manual-fetch` for the paper. |
| `in_progress` (`run status`: `interrupted`) | The run stopped mid-paper | Rerun the same command and output; leftovers move to `.arp-interrupted/`. |

Agent review, user download, missing configuration, rate limits, retryable errors, and permanent failures remain distinct states. Use `arp run status --run <directory>` to inspect a run.

## Long commands

`manual-fetch --queue --watch`, an institution login, a large `discover corpus`, or a long `acquire` can outlast a host's command timeout. Start such a command with `arp --background <new-job-directory> <command> ...`; it returns at once. Then run `arp job status --job <job-directory> --wait 60` until `status` is `finished`, `stopped`, or `crashed`; `progress` shows the latest lines and `result` holds the JSON the command would have printed. Relay `progress` lines that ask the user to act. `arp job stop --job <job-directory>` ends the command as Ctrl+C would; `--force` kills it, and rerunning the command resumes. `arp job list` shows every job started on this machine with its status.

## Completion rules

- Preserve original BibTeX bytes, BOM, encoding, and line endings; decode only a parsing view. Never generate or repair a citation with an LLM or a metadata API.
- Verify DOI, title, year, author scope, and venue. Report ambiguous identities and partial evidence explicitly.
- The executing agent makes semantic decisions and records the actual host: v2 decisions set `reviewer` and `executor.host` to it, with model/version only when actually available. Never relabel another host as Codex or invent model metadata. Legacy Codex v1 review bytes and hashes stay unchanged.
- Acquire only the frozen `selected-papers.jsonl` bound by `selection-manifest.json`. Never edit it, remove a difficult paper from it, or lower relevance thresholds to fill a quota. Papers skipped with `--defer-host`, paused, or failed stay selected in `manual-download.csv` or `retryable-downloads.csv`.
- Produce Markdown only after the user explicitly requests it and approves a destination (`arp export-md`). Fetch, manual fetch, and corpus workflows produce no Markdown; research uses an internal MinerU cache.
- Library changes go through a reviewed `plan.json` and an explicit `arp library apply --plan <path>`; retain backups for rollback.
- Never claim an absolutely complete bibliography or complete venue coverage.

## Access boundaries

Read [source policies](references/source-policies.md) before changing an acquisition contract and [configuration](references/configuration.md) before adapting an institution.

- Never print, log, commit, or send credentials, tokens, cookies, browser storage, or decrypted values. Keep state and deliveries outside the public repository.
- IEEE uses an isolated visible browser profile for the selected institution. A credential is released only at the profile's exact configured hostname; stop on any other host, CAPTCHA, OTP, or incomplete login. A successful identity-provider login is separate from the return to IEEE, a verified download, and proof of institutional entitlement.
- Never automate ScienceDirect article pages or ScienceDirect organization-login flows, attach to the user's normal Chrome, read its profile, or export Cookie/session data. User authorization does not relax this boundary. Authorized users download the PDF and raw BibTeX themselves; `manual-fetch` handles the local files afterward and records `manual_publisher_download` provenance.
- Never use Crossref, OpenAlex, Semantic Scholar, a mirror, or generated BibTeX as the final citation artifact. Never bypass publisher or institution access controls, publish partial MinerU output, or overwrite a delivery without identity and hash validation.
