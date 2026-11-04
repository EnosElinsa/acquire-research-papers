# Acquisition workflows

Use this reference for single papers and explicit lists: `arp fetch` and `arp manual-fetch`. `arp` means `python <skill-directory>/scripts/arp.py`. Corpus and research batches use the same adapters; see [corpus mode](corpus-mode.md) and [research mode](research-mode.md). The universal access boundaries are in [SKILL.md](../SKILL.md#access-boundaries) and the per-publisher contracts in [source policies](source-policies.md).

Every delivery is a verified pair: the official publisher PDF and the publisher's raw BibTeX export, with provenance. Discovery services may nominate candidates; they never supply the final citation artifact. Delivery directories must be outside this public repository.

## Automatic fetch

```text
arp fetch --input <DOI-or-official-URL> --output <directory>
```

Use the output only when the JSON status is `delivered`. A title that is not uniquely resolved must go through discovery first. A DOI is resolved through doi.org with bounded retries; an Elsevier link-resolver target is mapped to its ScienceDirect article page. Supported automatic publishers are ACL Anthology, IJCAI proceedings, AAAI OJS, NeurIPS proceedings, PMLR, CVF Open Access, Springer Link (open access, or subscription papers on an entitled network), ACM Digital Library (when its pages answer non-browser requests), and IEEE Xplore with an institution profile or entitled network. NeurIPS, PMLR, and CVF papers need their landing-page URL: PMLR and CVF papers have no DOI, and NeurIPS DOIs resolve to Curran Associates. Corpus discovery supplies these URLs from the archives' official indexes; for a single `fetch`, pass the URL. A CVF page yields CVF's open-access version; a CVPR or ICCV DOI yields the IEEE Xplore version instead. See [sources](sources.md) for the tested scope.

A non-zero exit carries an `error_code`. Handle it with the result table in [SKILL.md](../SKILL.md#act-on-every-result): `unsupported_adapter` and `access_required` (exit 69) go to `manual-fetch`; `network_transient`, `rate_limited`, and `automation_error` (exit 75) can be retried; `contract_error` (exit 78) is reported. Publisher HTTP errors report only the status and hostname.

## IEEE Xplore

For subscribed IEEE content, use only the named institution profile configured by the current user through `arp config setup ieee`. Assisted access leaves authentication to the user in the dedicated visible browser. A CARSI automatic profile includes the exact CARSI option and IdP entity ID, identity-provider host, and form contract, and may include an official IEEE WAYF URL supplied by the institution. The repository provides no institution name, identity-provider host, form label, credential default, or WAYF default. If the profile is absent or the page contract does not match it, the paper becomes `access_required` and the batch continues; never guess an institution or selector.

One dedicated browser serves every IEEE paper of a run, so an institutional login is reused across papers. If the window is closed or the browser crashes, the next paper starts a new browser. `ARP_IEEE_REUSE_BROWSER=0` restores one browser per paper. Page steps (navigation, PDF request, citation export) are bounded at 120 seconds; waiting for the user to finish a visible login uses the profile timeout (900 seconds by default). A transient citation-export failure is retried in the same browser before the downloaded PDF is discarded.

Within a batch, requests to one publisher host are spaced by two seconds. A host is paused for the rest of the run after HTTP 429 or three consecutive transient failures (`host_paused`, retryable), and after an institution login failure (`access_required`), so credentials are never resubmitted paper by paper. Rerun the same command later; verified papers are skipped.

After the unauthenticated PDF attempt fails, enter the profile's exact `ResourceAccessUrl` before institution selection. Write and verify the configured CARSI IdP entity ID before submitting discovery. If the profile contains an institution-supplied `IeeeWayfUrl`, use that exact IEEE-hosted route after the initial institutional login; otherwise revisit only the same `ResourceAccessUrl`. Never click a portal card. Allow at most three total gateway visits for the CARSI fallback path. If a configured institutional continuation page appears, require exactly one accept/continue control and allow at most one reject control; process at most three consecutive same-host continuation stages because some IdPs separate terms acceptance from attribute release. Never click reject. If a stage exposes one consent checkbox, select it only through its unique associated label and verify its checked state. The configured accept/continue control is automatic by default; use `--no-accept-ieee-attribute-release` to keep the page visible for manual action instead. After either path, report `access_required` if the page remains incomplete. A PDF request is forbidden until the same browser context has returned to the exact `ieeexplore.ieee.org` host.

When IEEE access fails for a previously untested institution, keep the visible browser and use the returned error payload to report only the sanitized stage and hostname. Adapt the institution profile first: correct its exact CARSI option, entity ID, IdP hostname, accessible form labels, resource gateway, and continuation controls, then retry one representative paper. Do not add a school-name branch or selector to the generic script. Change `ieee-playwright.mjs` only when observation proves a new generic page shape that cannot be expressed by the profile; add a regression test for that page shape before the implementation change. Preserve the exact-host credential boundary, one credential submission, shared persistent context, three-visit gateway limit, reject-button prohibition, visible manual continuation, and query-value redaction throughout adaptation.

## Manual publisher download

Use `manual-fetch` when the user must download from the official page: subscribed ScienceDirect content, a publisher without an adapter, or any `access_required` paper. For ScienceDirect, configure the Elsevier API key once (`arp config setup elsevier`) so the expected identity can be resolved. Start the watcher before the user downloads the official PDF and raw BibTeX:

```text
arp manual-fetch --input <DOI-or-ScienceDirect-URL> --watch <downloads-directory> --output <directory>
```

The command opens only the canonical article page. The user completes organization login and clicks both downloads; the CLI takes over stable new files, verifies identity, copies the pair, and records `manual_publisher_download` provenance. If both files already exist, pass `--pdf` and `--bibtex` instead. This flow never invokes MinerU. A ScienceDirect Article Retrieval API 403 is never retried with browser cookies or scripted login.

For a paper queued in a batch's `manual-download.csv`, use the selection ID rather than editable CSV metadata, so the pair fills its reserved paths:

```text
arp manual-fetch --selection <selection-manifest.json> --key <selection-id> --output <delivery-root> --watch <downloads-directory>
```

## Markdown

Fetch and manual fetch produce no Markdown. `acquire research` uses a seven-day SHA-256 MinerU cache for internal reading and never copies it into a delivery. Export only after the user explicitly requests it and approves a destination:

```text
arp export-md --pdf <paper.pdf> --output <directory>
```
