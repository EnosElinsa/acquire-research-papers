# Security Policy

## Supported versions

Security fixes are applied to the latest release and the current `main` branch. Older releases are not maintained after a fixed release is available.

## Report a vulnerability

Use [GitHub's private vulnerability reporting](https://github.com/EnosElinsa/acquire-research-papers/security/advisories/new) for this repository. Do not open a public issue containing an account name, password, API token, cookie, browser profile, signed URL, institution session, or decrypted value.

Include the affected version, operating system, the smallest reproducible sequence, and a redacted description of the observed host or redirect. Replace every secret and URL query string before attaching logs. Please allow time for triage before public disclosure.

If private reporting is unavailable, open a public issue containing only a request for a private contact channel and no vulnerability details.

## Credential boundary

This repository ships no credentials. New installations use explicitly editable local credential files outside the repository. `arp config path` reports the platform configuration root (`ARP_CONFIG_ROOT` may override it). API values live in one selected `.env`; named institution credentials live only in `credentials/<profile-id>.env`. Files contain plaintext and are restricted to the current user before values are written. Do not commit, share, or include populated files in logs or release assets. Only empty public templates are distributed. Saving a password does not enable automatic login.

API input uses an explicit process-environment snapshot over one selected dotenv file, without upward search, shell execution, or interpolation. File selection is `--env-file`, then `ARP_ENV_FILE`, then the default `.env`. Status exposes configured booleans, never values. Parsing errors report only paths/field names/line numbers. Institution credentials do not merge with API values or another profile.

Existing Windows DPAPI installations retain their legacy backend and original store under the detected data root. Migration requires explicit `arp config migrate --from dpapi` on the original Windows account. It preserves the original store, rejects conflicting destination keys without overwriting them, and reports key names only. There is no silent backend fallback. New runtime data uses the application's platform-data root; existing legacy roots remain compatible.

Authenticated browser adapters and API-key readers fail closed:

- An IEEE credential may be released only when the current hostname exactly matches the identity-provider hostname in the current user's institution profile.
- The Elsevier metadata API key may be released only to exact host `api.elsevier.com`.
- The Semantic Scholar API key may be released only to exact host `api.semanticscholar.org`.
- The OpenAlex API key may be released only to exact host `api.openalex.org`.
- Publisher artifacts must remain on the exact hosts defined in [source policies](skills/acquire-research-papers/references/source-policies.md).
- IEEE defaults to manual login in a dedicated visible browser. CAPTCHA, OTP, and unsupported page shapes require user action; automatic credential submission is not repeated. An unexpected credential host is rejected. Artifact identity mismatches prevent delivery.
- Named IEEE profiles keep independent browser sessions and credential references. Switching a profile does not copy another institution's session or credentials.
- Library changes require a hash-bound plan, source/destination rechecks, backups, and a per-library apply lock. A modified source or output is a conflict, not permission to overwrite it.
- The thin-skill launcher verifies the exact release-wheel SHA-256 before installation. The safe copy installer refuses Git checkout targets and links.
- Host doctor defaults to local checks. Optional remote reachability and host-version execution require explicit flags; neither establishes host loading, API entitlement, or institutional access. Shared review v2 records identify the real executing host and available model metadata without rewriting legacy records or hashes.

The project never attaches to a user's everyday browser profile and never exports browser cookies. ScienceDirect organization login and download clicks are user-driven; the manual handoff begins from a directory snapshot and handles only local PDF/BibTeX files after download.

## Scope

Reports about credential exposure, redirect validation, path traversal, unsafe artifact replacement, unredacted logs, dependency integrity, or publisher-host confusion are security issues. Publisher layout drift and unsupported sources without a security impact belong in ordinary issues.
