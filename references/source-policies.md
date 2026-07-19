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

Use the dedicated persistent Playwright profile in headful/off-screen Chrome because IEEE rejects the headless browser fingerprint. Read current metadata from `window.xplGlobal.document.metadata`, with legacy citation meta tags only as a fallback. Request the PDF iframe URL and `/rest/search/citation/format` through the same browser-context request client with `maxRedirects: 0`; the citation request must use `download-bibtex` and preserve the returned `data` string exactly.

Try one authorized Guangxi University CARSI credential submission only after the unauthenticated PDF attempt fails. A pre-credential Chrome navigation error may retry once. On the exact `idp.gxu.edu.cn` attribute-release page titled `信息发布`, accept the unique `接受` action without changing the long-term consent preference. Never release credentials to another host. A free/open PDF transient and an already-authenticated PDF transient may each retry once without repeating authentication.

### ACM Digital Library

Require exact `dl.acm.org` landing/PDF hosts and a page-exposed `/action/exportCiteProcCitation` BibTeX export for the same DOI. Parse the publication type or track before corpus inclusion. If ACM blocks the non-browser page request, use a dedicated publisher browser contract; do not substitute Crossref BibTeX.

### ScienceDirect

Use exact `www.sciencedirect.com` article, `pdfft`, and `/sdfe/arp/cite` endpoints for the same PII. Try open access or the current South China Agricultural University campus/IP entitlement before reading an institutional credential.

When direct access returns `access_required`, the dedicated off-screen browser may try the university's official WebVPN once. Release the `sciencedirect_scau` credential only while the current hostname exactly equals `vpn.scau.edu.cn`, submit it once, and require the browser to return to `www-sciencedirect-com-s.vpn.scau.edu.cn`. Retrieve the PDF and raw `/sdfe/arp/cite` BibTeX through that exact proxy host while recording canonical `www.sciencedirect.com` publisher URLs. Stop on CAPTCHA, OTP, an unknown host, an incomplete login, metadata/PII mismatch, or a redirect away from the exact proxy.

The [university remote-access instructions](https://lib.scau.edu.cn/2021/0415/c14674a298762/page.htm) state that Elsevier full text may require the aTrust client when WebVPN is insufficient. In that case return `atrust_required`; do not install, launch, or automate aTrust without separate user authorization, and never report the WebVPN login alone as successful paper access.

### Direct official sources

Use the generic adapter only when the publisher page exposes unique citation metadata, one official PDF, and one official BibTeX link on approved hosts. Ambiguity is a page-contract failure.

## Page drift

For a named phase failure, save only the minimal non-sensitive page structure needed for a fixture. Prefer stable metadata, hrefs, data attributes, and exact accessible names. Change the narrow contract and its test together. Never broaden an authentication host while repairing a selector.
