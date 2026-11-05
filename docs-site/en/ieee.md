# IEEE institutional access

IEEE uses a dedicated visible Chrome profile because authenticated access and PDF requests must share one isolated browser context. [Configuration](configuration.md#named-institution-profiles) shows how to create, select, and check a named institution profile.

## How a CARSI login proceeds

The workflow first tries the paper without reading credentials. If entitlement is missing, it:

1. enters the institution profile's exact CARSI IEEE resource gateway;
2. selects the exact configured institution option and writes and verifies its IdP entity ID;
3. releases the selected profile's credential only on the exact configured IdP hostname and submits it at most once;
4. handles either a single continue control or an accept/reject attribute-release page, never clicking reject;
5. revisits only the configured resource gateway when CARSI returns without IEEE entitlement;
6. requires the same context to return to the exact `ieeexplore.ieee.org` host before requesting PDF and BibTeX.

A configured accept/continue control is automatic by default. Pass `--no-accept-ieee-attribute-release` to keep the visible page available for manual completion.

## Adapting a new institution

The public script contains no university-name branch or shared credential. A new institution should be adapted through its profile first: exact CARSI option, entity ID, IdP hostname, accessible form labels, resource gateway, and continuation controls. Keep the visible browser open, use only sanitized stage/hostname diagnostics, and retry one representative paper after each correction.

Modify the generic browser script only when a visible page proves a new reusable page shape that cannot be represented by the profile. Add a regression fixture first. Preserve exact-host credential release, one credential submission, the three-visit gateway limit, shared cookies, reject-button prohibition, and query-value redaction.

To propose support for a new institution, open an [institution request](https://github.com/EnosElinsa/acquire-research-papers/issues/new?template=institution.yml) with sanitized diagnostics only.
