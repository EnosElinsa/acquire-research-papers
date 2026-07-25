# Discovery API Credentials and DOI Abstract Enrichment Design

Date: 2026-07-25

## Objective

Make discovery API authentication persistent, secure, and convenient while improving abstract completion for DOI-identified corpus candidates. The implementation must remain provider-neutral and must not alter an existing frozen selection in place.

Success means:

- one Windows DPAPI-encrypted credentials file stores every acquisition credential scope;
- OpenAlex, Semantic Scholar, and Elsevier API keys can be configured through hidden interactive prompts;
- each key is released only for its exact approved API hostname;
- corpus discovery can enrich missing abstracts through Semantic Scholar and OpenAlex DOI lookup;
- one enricher being unavailable or rate-limited does not prevent later enrichers from running;
- interactive discovery can report sanitized phase progress without changing its machine-readable stdout contract;
- existing IEEE, MinerU, Elsevier, and unknown legacy scopes survive every update.

## Considered Approaches

### Extend the existing DPAPI payload

Use `%LOCALAPPDATA%\Codex\secrets\acquire-research-papers\secrets.clixml` as the single credential store. Add `api_keys.semantic_scholar` and `api_keys.openalex` beside the existing `api_keys.elsevier` scope. This preserves the package's current security model and migration behavior.

This is the selected approach.

### Windows Credential Manager

Credential Manager would also encrypt secrets, but it would introduce a second credential backend, additional deployment dependencies, and a migration path for existing DPAPI scopes. It offers no material benefit for this local package.

### Plaintext environment or configuration file

An `.env`, YAML, or JSON file would be convenient but could leak through shell history, logs, backups, support bundles, or accidental commits. Plaintext persistence is not permitted.

## Credential Model

The existing schema-version-1 DPAPI payload remains structurally compatible:

```text
Scopes
├── ieee_institution
├── mineru
└── api_keys
    ├── elsevier
    ├── semantic_scholar
    └── openalex
```

`secret-store.ps1` will expose provider-neutral API-key setters and validators. Provider names are selected from a closed mapping; arbitrary scope names are rejected. Updating one key loads the existing payload, changes only the selected property, and atomically saves the payload. Existing and unknown scopes are preserved.

`setup-discovery-api-keys.ps1` will prompt without echo for OpenAlex, Semantic Scholar, and Elsevier keys. The user may skip a provider, retain an existing key, or replace it. Output contains only provider names, `configured`/`skipped` state, and the credential-file path.

`read-discovery-api-key.ps1` will require both a provider identifier and an expected hostname. The approved mapping is exact:

| Provider | Approved hostname |
| --- | --- |
| `semantic_scholar` | `api.semanticscholar.org` |
| `openalex` | `api.openalex.org` |
| `elsevier` | `api.elsevier.com` |

Schemes, ports, paths, trailing-dot variants, wildcard forms, and mismatched provider-host pairs are rejected. The script emits only the requested plaintext key to its authorized child process and clears local references afterward.

The existing Elsevier setup and reader scripts remain compatible. They may delegate to the generic implementation, but their command-line contract and exact-host protection remain unchanged.

## Python Credential Bridge

Introduce a provider-neutral DPAPI API-key provider in Python. It invokes the exact reader script with a provider and approved hostname, captures the key in memory, and never places it in a command line, URL, provenance record, diagnostic, or parent-process environment.

Production application construction obtains optional discovery keys through this bridge. A missing scope is treated as an unconfigured optional provider. An invalid payload, host mismatch, or reader failure is reported as sanitized configuration status; decrypted output is never included in an exception message.

Environment variables remain a compatibility override for controlled CI and tests. DPAPI is the default for local Windows execution. Neither source is printed by `credentials status`.

## Credential Status

Add `arp credentials status`. It reports only whether these scopes are configured:

- IEEE institution profile and credential;
- MinerU token;
- Elsevier API key;
- Semantic Scholar API key;
- OpenAlex API key.

Status inspection validates encrypted scope shape without decrypting or emitting secret values.

## OpenAlex DOI Enrichment

Extend `OpenAlexClient` with `lookup_dois(dois)` using the official works filter contract:

```text
GET /works?filter=doi:<doi-1>|<doi-2>|...&per_page=100&api_key=<key>
```

The implementation:

- normalizes and de-duplicates DOI values;
- accepts at most 100 DOI values per client call;
- requests only the work fields needed to construct `CandidateMetadata`;
- reconstructs `abstract_inverted_index` into plain abstract text;
- returns zero or one candidate per recognized DOI;
- records only the endpoint without query parameters in provenance and exceptions;
- never exposes the API key or the full query URL.

Register OpenAlex as a `DoiBatchEnrichmentProvider` with batch size 100 after Semantic Scholar. The coordinator already merges one enricher before invoking the next, so OpenAlex receives only candidates that still lack abstracts. A Semantic Scholar diagnostic or rate limit does not stop OpenAlex.

Elsevier Abstract Retrieval is intentionally deferred until the remaining post-OpenAlex gap is measured. If required, it will be added as another generic DOI enricher using the same credential and host-boundary abstractions, without ScienceDirect browser automation.

## Progress Reporting

Add an opt-in `--progress` flag to corpus discovery. Progress messages go to stderr; the final JSON result remains the only stdout record. Messages are bounded to phase and aggregate counts:

- request validated;
- provider enumeration started/completed;
- DOI enrichment provider started/completed;
- candidates merged;
- artifacts and manifest written.

No URL query string, DOI batch contents, response payload, credential status detail, or secret value is included. Interactive setup prints a success line immediately after the encrypted payload is saved so a hidden-input prompt never appears to hang.

## Discovery and Review Data Flow

1. Configure keys once through the interactive DPAPI setup script.
2. Run corpus discovery into a new output directory with `--progress`.
3. Enumerate official and Crossref venue/year slices.
4. Merge stable candidate identities.
5. Enrich missing DOI abstracts with Semantic Scholar, then OpenAlex.
6. Write a new immutable candidate/evidence snapshot and its hashes.
7. Compare `pending_abstract` counts by venue with the prior run.
8. Recreate semantic decisions against new evidence hashes.
9. Raise the preferred corpus target to 350 only after the abstract gap and accepted-pool capacity are verified.

An existing `selection-manifest.json` and delivery directory are never edited during enrichment.

## Error Handling

- Missing optional key: skip that provider and report `not_configured` in sanitized progress/status output.
- HTTP 429 or transient network failure: record a retryable diagnostic and continue with later enrichers.
- Invalid key or forbidden response: record a sanitized provider error without response headers, request query, or key.
- DPAPI reader or payload failure: stop credential setup; discovery continues without that optional provider only when the scope is simply absent.
- OpenAlex response without an abstract: leave the candidate `pending_abstract`.
- DOI identity conflict: retain existing coordinator conflict behavior and exclude the conflicting enrichment record.

## Test Plan

PowerShell regression tests will cover:

- storing all three API-key scopes in one DPAPI payload;
- replacing one key while preserving IEEE, MinerU, other API keys, and unknown scopes;
- hidden setup output never containing plaintext keys;
- exact provider-host release and denial of mismatches, schemes, ports, paths, trailing dots, and wildcard hosts;
- status output reporting only configured/missing state.

Python regression tests will cover:

- OpenAlex DOI normalization, de-duplication, and batches of at most 100;
- abstract reconstruction and candidate identity;
- missing and partial DOI results;
- key and query redaction from provenance, errors, and progress;
- Semantic Scholar rate limiting followed by successful OpenAlex enrichment;
- DPAPI key loading, optional missing scopes, and environment compatibility override;
- progress on stderr with unchanged final JSON stdout;
- the complete existing unit, PowerShell, and skill-layout suites.

## Delivery and Migration

No plaintext secret is committed. Existing users keep the same DPAPI file and can configure only missing providers. The old Elsevier command remains operational. Documentation will identify the unified setup command as the preferred path and retain individual setup commands for targeted replacement.

After tests pass, commit and push the implementation as a focused change to the global `acquire-research-papers` repository. The corpus enrichment run and its evidence artifacts remain outside Git in the student working directory.
