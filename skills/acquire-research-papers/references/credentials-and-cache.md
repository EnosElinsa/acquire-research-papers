# Credentials and cache

Load this reference before institutional access, API-key setup, or MinerU parsing.

## Task-scoped first use

Run `arp config status` before asking for configuration. It reports capability booleans only; `--details` adds non-secret profile/history details. File values are parsed in memory for presence checks and never returned. Legacy DPAPI status checks encrypted scope shape without decrypting secret values. `arp credentials status` is a compatibility alias. IEEE, MinerU, Elsevier, Semantic Scholar, and OpenAlex are optional and independent. Configure only a capability required by the current task. Never paste secret values into chat, an agent message, command arguments, logs, or the repository. A user may edit the selected local credential file directly. Run commands through `python <skill-directory>/scripts/arp.py`.

## Editable local configuration

New installations use file credentials. `platformdirs` chooses the OS configuration root; `ARP_CONFIG_ROOT` explicitly overrides it. Use `arp config path` for the actual resolved path rather than guessing a Windows, macOS, or Linux location.

```text
arp config init
arp config path
arp config edit
arp config edit --profile <profile-id>
arp config status
```

Initialization never overwrites existing files. Config/edit/setup/status output contains paths, key names and non-secret state only. Setup prompts are interactive and non-echoing; edit opens the chosen local file with `VISUAL`, `EDITOR`, or the OS editor. Populated credential files are plaintext, protected for the current user; keep them outside repositories, shared folders, public logs, and release bundles. This is an explicit local-editing choice, not OS keychain encryption.

```text
<config-root>/config.toml
<config-root>/.env
<config-root>/institutions/<profile-id>.json
<config-root>/credentials/<profile-id>.env
```

The root `.env` contains `SEMANTIC_SCHOLAR_API_KEY`, `OPENALEX_API_KEY`, `ELSEVIER_API_KEY`, and `MINERU_TOKEN`. A profile credential file contains only `INSTITUTION_USERNAME` and `INSTITUTION_PASSWORD`. Empty values mean unconfigured. Browser sessions remain in isolated browser directories, never credential files. [Empty API template](../templates/.env.example) and [empty institution template](../templates/institution.env.example) contain no secret values.

API precedence is explicit process environment → one selected dotenv file. Select that file using `--env-file <path>` → `ARP_ENV_FILE` → default `<config-root>/.env`. The command reads a snapshot once, does not search parent directories, does not merge additional dotenv files, does not execute shell code, and disables dotenv interpolation. Quotes, comments, special characters and non-ASCII values are data. A malformed file reports only path/field/line details, never its value. Institution credentials come only from the selected profile's referenced file; they are not taken from the API file or another institution.

Saving a password never enables automatic login. The institution mode and reviewed exact-host form contract control that separately. Keep profile selection explicit and user-interaction requirements unchanged.

## Legacy DPAPI compatibility and migration

An existing DPAPI store keeps its legacy backend; there is no silent plaintext fallback or implicit merging. `config.toml` records the backend after initialization. On the original Windows machine/account, run `arp config migrate --from dpapi` to migrate explicitly. The source store remains available. Destination conflicts are reported by key name without overwrite; resolve them locally before retrying. Non-Windows hosts cannot decrypt a Windows DPAPI store. Copying CLIXML does not migrate it.

## Global runtime paths

New runtime state uses the application's own platform data root, with `ARP_DATA_ROOT` available for explicit isolation. Existing legacy roots under `%LOCALAPPDATA%\Codex` are detected for compatibility. The concrete subdirectories remain:

- registry and runs: `paper-acquisition\`;
- parsed cache: `cache\acquire-research-papers\`;
- legacy encrypted scopes, when selected: `secrets\acquire-research-papers\secrets.clixml`;
- dedicated browser profiles: `browser-profiles\acquire-research-papers\`;
- pinned browser dependencies: `deps\acquire-research-papers\`.

The SQLite registry stores metadata, URLs, hashes, states, paths, provenance, and evidence. It never stores credentials, cookies, tokens, or full text.

## Institution and provider boundaries

Run `arp config setup ieee --profile <name> --mode assisted` for ordinary guided institutional access. Use an explicit observed non-secret `--contract` only when configuring automatic CARSI access; it supplies the exact CARSI search and option text, IdP entity ID and hostname, form labels, resource route, and optional continuation controls. `--save-credentials` prompts securely in the terminal and saves to the selected file backend; an existing legacy store requires explicit migration before new file writes. Configure MinerU separately with `arp config setup mineru`. Non-secret named profiles are JSON outside the repository. There are no institution defaults. See [configuration](configuration.md) for selection, login, doctor, inspection, and migration.

Legacy developer compatibility helpers `setup-ieee-institution.ps1`, `setup-secrets.ps1`, `migrate-legacy-secrets.ps1`, `update-ieee-institution-entity.ps1`, and `update-ieee-institution-route.ps1` are bundled in the Python wheel's `_scripts` directory. They are not files in the installed thin skill's `scripts` directory. Normal users invoke `arp config setup ieee` and named-profile commands. Legacy entity/route updates preserve existing DPAPI credentials and other scopes without requiring the password again.

For CARSI contracts, the resource URL must use exact HTTPS host `ds.carsi.edu.cn`; an optional institution-supplied IEEE WAYF URL must use exact HTTPS host `ieeexplore.ieee.org`. Accept and reject control names are separate so automation can prove it never selected rejection. Update a named profile with explicit `arp config setup ieee --profile <name> --replace --contract <contract.json>`; non-secret contract updates never grant permission to reuse another profile's credentials.

For an untested institution, keep the visible browser open and retain only the sanitized stage and hostname transition evidence. Update the institution profile first and retry one paper. Do not add school-specific code. Change the generic browser flow only when the visible evidence establishes a new generic page shape that cannot be expressed by the profile; add a regression test before the implementation. Never store query values, SAML state, signed URLs, cookies, or credentials in the adaptation report.

Legacy `ieee_institution` may hold an older routing profile and credential; named profiles reference isolated protected entries through `ieee_profiles:<id>`. The non-secret bridge may return only configured organization/page-contract fields. The browser writes and verifies the exact configured CARSI entity ID before discovery submission so a delayed typeahead cannot silently submit an empty route. The credential bridge releases username/password only at the profile's exact credential hostname; lookalikes, trailing dots, schemes, ports, paths, and wildcards are rejected. It submits credentials once, clears in-memory strings, and leaves CAPTCHA/OTP/incomplete login to visible user action. An institution-supplied WAYF URL must use exact HTTPS `ieeexplore.ieee.org`; otherwise the transition revisits only the configured resource route, with three gateway visits at most. Never click a portal card, guess selectors, or reuse another profile's credential/session.

`MINERU_TOKEN` comes from the selected API snapshot or explicit legacy provider and is injected only into the precision CLI child's environment. Do not export it into unrelated parent processes. Legacy DPAPI uses a child-process bridge.

API providers remain independent. Add or replace a selected provider through `arp config setup <provider>`; other fields and comments are preserved. The wheel-internal compatibility helpers `setup-discovery-api-keys.ps1` and `setup-elsevier-api-key.ps1` retain the legacy DPAPI store. Exact-host readers release keys only for `api.elsevier.com`, `api.semanticscholar.org`, or `api.openalex.org`. Keys never appear in command arguments, logs, provenance, or persisted request URLs.

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

Successful parses are addressed by PDF SHA-256. `metadata.json` records mode, paths, the Markdown hash, creation time, and last access. Entries expire seven days after last access. Internal research parsing does not copy Markdown into a delivery. Export only the successful result directory after an explicit user request.

Cache reuse checks the recorded Markdown hash. Changed text or a legacy entry without that hash requires inspection: preserve the entry if needed, remove that one cache entry explicitly, and parse the original PDF again. The runtime does not silently bless changed text or rewrite existing evidence hashes. A persistent OS advisory lock prevents competing parses and is released automatically after a process exits. An older `parse.lock` is preserved; confirm the older parser has stopped before explicitly removing that legacy lock and retrying.
