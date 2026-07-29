# Credentials and cache

Load this reference before institutional access, API-key setup, or MinerU parsing.

## Task-scoped first use

Run `arp config status` before asking for configuration. It inspects only whether each encrypted scope has the expected object shape and returns booleans; it does not convert a `SecureString` to plaintext. `arp credentials status` is a compatibility alias. IEEE, MinerU, Elsevier, Semantic Scholar, and OpenAlex are optional and independent. Configure only a capability required by the current task, and never ask a user to paste a key into chat, a command argument, an environment file, or the repository.

## Global runtime paths

Runtime state is outside the Git repository under `%LOCALAPPDATA%\Codex`:

- registry and runs: `paper-acquisition\`;
- parsed cache: `cache\acquire-research-papers\`;
- encrypted scopes: `secrets\acquire-research-papers\secrets.clixml`;
- dedicated browser profiles: `browser-profiles\acquire-research-papers\`;
- pinned browser dependencies: `deps\acquire-research-papers\`.

The SQLite registry stores metadata, URLs, hashes, states, paths, provenance, and evidence. It never stores credentials, cookies, tokens, or full text.

## DPAPI scopes

Run `scripts/setup-ieee-institution.ps1` in an interactive terminal to configure IEEE institutional access. The user supplies the institution name, exact CARSI search and option text, exact CARSI IdP entity ID, exact identity-provider hostname, login form labels, post-login CARSI IEEE resource URL, optional exact attribute-release title plus accept/reject control names, and credential. Configure MinerU separately with `scripts/setup-mineru-token.ps1`; `scripts/setup-secrets.ps1` remains an interactive convenience wrapper for both. Credentials and tokens use non-echoing prompts and are stored in a Windows DPAPI-encrypted CLIXML payload. The repository contains no institution defaults. `scripts/migrate-legacy-secrets.ps1` can rewrap an earlier IEEE payload after the user supplies the generic profile fields, without printing plaintext.

Profiles created before the CARSI entity-ID contract can be upgraded with `scripts/update-ieee-institution-entity.ps1 -CarsiEntityId <exact-https-entity-id>`. The updater validates the new non-secret route field and atomically preserves the existing DPAPI credential and every other scope; it does not require the username or password again.

Use `scripts/update-ieee-institution-route.ps1` to add or change only the non-secret resource gateway and attribute-release contract on an existing profile. It preserves the existing DPAPI credential. The resource URL must use exact HTTPS host `ds.carsi.edu.cn`; accept and reject control names are stored separately so automation can prove it never selected rejection.

For an untested institution, keep the visible browser open and retain only the sanitized stage and hostname transition evidence. Update the institution profile first and retry one paper. Do not add school-specific code. Change the generic browser flow only when the visible evidence establishes a new generic page shape that cannot be expressed by the profile; add a regression test before the implementation. Never store query values, SAML state, signed URLs, cookies, or credentials in the adaptation report.

The `ieee_institution` scope contains the current user's profile and credential. The non-secret profile bridge may return only the configured organization and page contract, including the CARSI IdP entity ID. The browser writes and verifies that exact entity ID before CARSI discovery submission so a delayed typeahead script cannot silently submit an empty institution route. The credential bridge releases the username and password only after the current hostname exactly equals the profile's `CredentialHost`; lookalikes, trailing-dot forms, schemes, ports, paths, and wildcards are rejected. The browser enters the configured resource before institution selection, submits credentials once, clears in-memory strings, and stops on CAPTCHA, OTP, an unknown host, or an incomplete login. The resource transition may revisit only the same configured `ResourceAccessUrl`, with three total visits at most; it never discovers or clicks a portal card. If an institution's page does not match the configured labels, defer the paper instead of guessing selectors.

The `mineru` scope contains the MinerU API token. It is read through a child-process bridge and injected only into the precision CLI child's `MINERU_TOKEN` environment. Do not export it in the parent shell.

The optional `api_keys` scope can contain independent `elsevier`, `semantic_scholar`, and `openalex` secure values. Add or replace selected providers with `scripts/setup-discovery-api-keys.ps1 -Provider <provider>`; the update preserves `ieee_institution`, `mineru`, other API providers, and unknown legacy scopes. The compatibility script `setup-elsevier-api-key.ps1` delegates to the same store. Exact-host readers release a value only for `api.elsevier.com`, `api.semanticscholar.org`, or `api.openalex.org` as mapped to that provider. Keys never appear in command arguments, logs, provenance, or persisted request URLs.

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

The MinerU child environment appends both `mineru.oss-cn-shanghai.aliyuncs.com` and `cdn-mineru.openxlab.org.cn` to `NO_PROXY` and `no_proxy`. Preserve existing exclusions and remove duplicates case-insensitively. Do not change the parent process environment.

Successful parses are addressed by PDF SHA-256. `metadata.json` records mode, paths, creation time, and last access. Entries expire seven days after last access. Internal research parsing does not copy Markdown into a delivery. Export only the successful result directory after an explicit user request.
