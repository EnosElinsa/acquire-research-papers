# Source policies

Load this reference before acquiring from a publisher or changing an adapter.

## Universal contract

Start from a canonical DOI or confirmed publisher landing page. Follow only exact hosts approved by the selected adapter, validate every redirect before sending another request, and strip sensitive headers when a host changes. A delivery contains:

- the publisher-hosted PDF;
- the publisher's raw BibTeX export;
- provenance with landing, PDF, and BibTeX URLs plus hashes.

Crossref, OpenAlex, Semantic Scholar, search engines, repositories, and mirrors are discovery sources. They are not final PDF/BibTeX authorities. A public repository PDF may be used only when it is the official venue archive covered by an adapter, such as ACL Anthology or IJCAI proceedings.

## Provider contracts

### ACL Anthology

Require an exact Anthology ID. The `.pdf`, `.bib`, DOI, title, authors, year, and proceedings metadata must agree with that ID.

### IJCAI proceedings

Require one visible PDF link, one visible BibTeX link, matching DOI, and a parsed track. Main-track requests must reject demo, poster, tutorial, workshop, or other non-target tracks.

### IEEE Xplore

Use the dedicated persistent Playwright profile in headful Chrome because IEEE rejects the headless browser fingerprint. Keep the window visible whenever institutional user action may be required. Read current metadata from `window.xplGlobal.document.metadata`, with legacy citation meta tags only as a fallback. The stamp page may expose either `/stampPDF/getPDF.jsp` or a direct `.pdf` iframe. Resolve either relative form against the stamp page, require the exact `ieeexplore.ieee.org` hostname, and request it and `/rest/search/citation/format` through the same browser-context request client with `maxRedirects: 0`; the citation request must use `download-bibtex` and preserve the returned `data` string exactly. Treat child-process, PDF-request, and citation-request timeouts as retryable failures. Failure diagnostics may record only a phase, reason, status, and media type; never record redirect or signed-URL query values.

Try one authorized CARSI credential submission only after the unauthenticated PDF attempt fails and only when the current user has configured an institution profile. Enter the profile's exact HTTPS `ResourceAccessUrl` on `ds.carsi.edu.cn` first so the SAML return target survives institution selection. Select the exact configured CARSI option, write and verify its configured HTTPS IdP entity ID in CARSI's routing field, require the redirect hostname to equal the configured credential host, and use only the configured form labels. If an existing IdP session redirects without exposing the username field, do not read credentials. CARSI login alone does not establish IEEE entitlement. Re-enter only the same configured resource URL after CARSI or attribute release returns without IEEE entitlement; never click a portal card. Stop after at most three total resource visits and include only sanitized transition hosts/URLs in the error.

An optional institutional-continuation contract consists of an optional exact page title, an exact accept/continue control `name`, and an optional exact reject control `name`. Require exactly one accept/continue control and at most one reject control, never click reject, and click the configured accept/continue control automatically by default. This covers both single-button continuation pages and accept/reject attribute-release pages. With `--no-accept-ieee-attribute-release`, leave the headful page visible for the full configured timeout; continue automatically if the user completes the step, otherwise report `attribute-release-required`. After the resource gateway or an accepted release, require the exact `ieeexplore.ieee.org` hostname before any PDF retry; otherwise report `institutional-return`. Never infer an institution, broaden a hostname, guess a selector, or reuse another user's profile. A pre-credential Chrome navigation error may retry once; a free/open PDF transient and an already-authenticated PDF transient may each retry once without repeating authentication. On any profile mismatch, defer the paper as `access_required` and continue the corpus run.

### ACM Digital Library

Require exact `dl.acm.org` landing/PDF hosts and a page-exposed `/action/exportCiteProcCitation` BibTeX export for the same DOI. Parse the publication type or track before corpus inclusion. If ACM blocks the non-browser page request, use a dedicated publisher browser contract; do not substitute Crossref BibTeX.

### ScienceDirect

ScienceDirect acquisition is manual-only. Use `manual-fetch` for exact `www.sciencedirect.com` PII articles; ordinary `fetch` must not request or automate the article page, even when the current network might be entitled.

Resolve the expected PII, DOI, title, year, venue, and first creator through the official Elsevier Scopus Search API. Snapshot the selected download directory before opening the canonical article page. The user completes organization login and downloads the PDF plus the publisher's raw BibTeX in a normal browser. Consider only new or changed stable files, verify PDF identity and the raw citation, deduplicate by SHA-256, and require exactly one valid pair. Record `manual_publisher_download` provenance and preserve the source files.

Never automate the ScienceDirect page, submit an organization login, attach to normal Chrome, read a browser profile, export Cookie/session data, or inject browser state into an API request. Do not retry an Article Retrieval API 403 with browser credentials. Crossref and other discovery metadata cannot replace the raw `/sdfe/arp/cite` BibTeX.

### Direct official sources

Use the generic adapter only when the publisher page exposes unique citation metadata, one official PDF, and one official BibTeX link on approved hosts. Ambiguity is a page-contract failure.

## Page drift

For a named phase failure, save only the minimal non-sensitive page structure needed for a fixture. Prefer stable metadata, hrefs, data attributes, and exact accessible names. Change the narrow contract and its test together. Never broaden an authentication host while repairing a selector.
