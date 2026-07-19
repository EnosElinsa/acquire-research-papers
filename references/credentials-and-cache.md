# Credentials and cache

Load this reference before institutional access, API-key setup, or MinerU parsing.

## Global runtime paths

Runtime state is outside the Git repository under `%LOCALAPPDATA%\Codex`:

- registry and runs: `paper-acquisition\`;
- parsed cache: `cache\acquire-research-papers\`;
- encrypted scopes: `secrets\acquire-research-papers\secrets.clixml`;
- dedicated browser profiles: `browser-profiles\acquire-research-papers\`;
- pinned browser dependencies: `deps\acquire-research-papers\`.

The SQLite registry stores metadata, URLs, hashes, states, paths, provenance, and evidence. It never stores credentials, cookies, tokens, or full text.

## DPAPI scopes

Run `scripts/setup-secrets.ps1` in an interactive terminal for first-time setup. Values are entered through non-echoing prompts and stored as a Windows DPAPI-encrypted CLIXML payload. `scripts/migrate-legacy-secrets.ps1` can rewrap the earlier IEEE payload under the new scope schema without printing plaintext.

The `ieee_gxu` scope contains the Guangxi University credential. The browser bridge releases it only after the current hostname exactly equals `idp.gxu.edu.cn`. It submits once, clears in-memory strings, and stops on CAPTCHA, OTP, an unknown host, or an incomplete login.

The `mineru` scope contains the MinerU API token. It is read through a child-process bridge and injected only into the precision CLI child's `MINERU_TOKEN` environment. Do not export it in the parent shell.

The optional `api_keys.elsevier` scope contains the Elsevier API key used for official metadata resolution. Add or replace it with `scripts/setup-elsevier-api-key.ps1`; the update preserves `ieee_gxu`, `mineru`, and unknown legacy scopes. The exact-host reader releases it only for `api.elsevier.com`. The key is never sent to ScienceDirect or exposed in a URL, command line, log, or provenance record.

The manual ScienceDirect workflow stores no university credential. Organization login remains inside the user's normal browser, and the CLI receives only the PDF and raw BibTeX files the user downloads. Article Retrieval or Authentication API entitlement is optional and is not inferred from a working Search API key.

## Browser isolation

Automated publishers must use only the skill's dedicated persistent profiles. Never locate, attach to, enumerate, or copy the user's normal Chrome profile. Cookies remain inside the browser context. PDF and citation requests disable automatic redirects so headers cannot be forwarded off the approved host. ScienceDirect is not an automated browser adapter: `manual-fetch` may open its canonical page but never controls or inspects that browser session.

Playwright Core is fixed at version `1.61.1`, its npm tarball and integrity hash are pinned, lifecycle scripts are disabled, and installation occurs only under the global dependency root.

## MinerU cache

Precision output and flash fallback output use separate directories. Flash is allowed once only when the precision log simultaneously identifies:

- result ZIP/archive download;
- exact host `cdn-mineru.openxlab.org.cn`;
- EOF/TLS/handshake transport failure.

The fallback receives no token. `429` or quota signals stop immediately with exit code 75 behavior.

Process logs must redact the API token and remove every URL query string before an error reaches stdout, stderr, a manifest, or an agent response. A transport EOF/TLS failure while uploading to the exact MinerU OSS host may retry precision once. This does not authorize flash fallback; flash remains limited to the exact result-CDN failure above.

Successful parses are addressed by PDF SHA-256. `metadata.json` records mode, paths, creation time, and last access. Entries expire seven days after last access. Internal research parsing does not copy Markdown into a delivery. Export only the successful result directory after an explicit user request.
