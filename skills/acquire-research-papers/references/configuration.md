# Named IEEE institutions and provider setup

Use `python <skill-directory>/scripts/arp.py` wherever examples say `arp`. The launcher and release wheel carry all runtime helpers; the installed skill is not a developer repository.

Start with `arp config status`, which reports capability booleans only. Add `--details` for non-secret active-profile and historical-validation details. Neither form decrypts key values or performs a live entitlement test. Configure only the capability this task needs.

## Institution profiles

```text
arp config setup ieee --profile university-a --organization "My institution" --mode assisted --entry-url https://library.example.org/ieee
arp config ieee list
arp config ieee use university-a
arp config ieee login --profile university-a
arp config ieee doctor --profile university-a --reference https://ieeexplore.ieee.org/document/1234567
```

The entry URL must be the exact HTTPS institutional/library/IEEE route supplied by the user or observed in the authorized institutional workflow. There are no built-in schools, IdP hostnames, selector defaults, or guessed routes.

- `direct` uses an already authorized network/proxy route; access still requires a verified publisher response.
- `assisted` opens a dedicated visible browser; the user completes credentials, CAPTCHA, OTP, or consent. The agent does not receive credential values.
- `carsi` requires an explicit observed non-secret form contract. Use `--contract <contract.json>` with the exact `credentialHost`, CARSI route/option/entity ID, form labels, and continuation controls. `--save-credentials` prompts securely in the user's terminal and stores a named DPAPI credential. No automatic saved credential submission is permitted without a validated contract.

`--no-login` saves a profile without opening a session. `--inspect` returns candidate non-sensitive form structure (names/types/labels), without values or HTML; review it before updating the contract. Replacing a profile requires `--replace`. Each named profile has an isolated persistent browser directory. Switching profiles changes only the selected reference; cookies are not copied between profiles. Legacy configuration is migrated into a `legacy-default` profile when available.

The non-secret profile shape is in [institution-profile.schema.json](../schemas/institution-profile.schema.json). Credentials stay in the protected secret store, referenced by profile ID. Runtime profiles, registry, secrets, browser contexts, and caches stay outside the repository and installed skill.

## Interpret validation correctly

Keep these states separate: profile configured; identity-provider login completed; returned to exact IEEE host; PDF and native BibTeX verified; institutional entitlement established. An open-access article can verify a download without proving institutional entitlement. Historical results include a timestamp and never become current live-session proof. `doctor` tests one representative reference; an access failure remains a diagnostic, not permission to broaden selectors or hostnames.

Failed `doctor` checks also return timestamped `diagnostics` and replace the previous historical result, including when native citation validation fails. Unknown stages remain null. Transport failures remain retryable download errors; they do not trigger another credential submission.

For a new institution, retain the visible browser and report only the sanitized stage and hostname. Adapt the institution profile first, then retry one representative paper. Change generic browser code only when observed evidence establishes a new generic page shape that cannot be expressed by the profile; add a regression test first. Never capture query values, SAML payloads, cookies, or credential values.

## Optional independent providers

```text
arp config setup mineru
arp config setup elsevier
arp config setup semantic_scholar
arp config setup openalex
arp config status
```

Prompts are interactive and non-echoing. IEEE browser access and DPAPI setup currently require Windows; public discovery and library operations are portable. Provider setup preserves other secret scopes. See [credentials and cache](credentials-and-cache.md) for host boundaries, legacy compatibility helpers, and MinerU transport limits.
