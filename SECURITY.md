# Security Policy

## Supported versions

Security fixes are applied to the latest release and the current `main` branch. Older releases are not maintained after a fixed release is available.

## Report a vulnerability

Use GitHub's private vulnerability reporting for this repository. Do not open a public issue containing an account name, password, API token, cookie, browser profile, signed URL, institution session, or decrypted value.

Include the affected version, operating system, the smallest reproducible sequence, and a redacted description of the observed host or redirect. Replace every secret and URL query string before attaching logs. Please allow time for triage before public disclosure.

If private reporting is unavailable, open a public issue containing only a request for a private contact channel and no vulnerability details.

## Credential boundary

This repository ships no credentials. Runtime secrets are stored outside the repository under `%LOCALAPPDATA%\Codex\secrets\acquire-research-papers` and encrypted with Windows DPAPI for the current user.

Authenticated browser adapters and API-key readers fail closed:

- Guangxi University credentials may be released only to exact host `idp.gxu.edu.cn`.
- The Elsevier metadata API key may be released only to exact host `api.elsevier.com`.
- Publisher artifacts must remain on the exact hosts defined in [`references/source-policies.md`](references/source-policies.md).
- CAPTCHA, OTP, an unexpected host, an incomplete login, or a metadata mismatch stops the run.

The project never attaches to a user's everyday browser profile and never exports browser cookies. ScienceDirect organization login and download clicks are user-driven; the manual handoff begins from a directory snapshot and handles only local PDF/BibTeX files after download.

## Scope

Reports about credential exposure, redirect validation, path traversal, unsafe artifact replacement, unredacted logs, dependency integrity, or publisher-host confusion are security issues. Publisher layout drift and unsupported sources without a security impact belong in ordinary issues.
