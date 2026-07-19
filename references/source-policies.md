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

Use the dedicated Playwright profile. Request the PDF iframe URL and `/xpl/downloadCitations` through the same browser-context request client with `maxRedirects: 0`. Try one authorized Guangxi University CARSI authentication only after the unauthenticated PDF attempt fails.

### ACM Digital Library

Require exact `dl.acm.org` landing/PDF hosts and a page-exposed `/action/exportCiteProcCitation` BibTeX export for the same DOI. Parse the publication type or track before corpus inclusion. If ACM blocks the non-browser page request, use a dedicated publisher browser contract; do not substitute Crossref BibTeX.

### ScienceDirect

Use exact `www.sciencedirect.com` article, `pdfft`, and `/sdfe/arp/cite` endpoints for the same PII. Try open access or the current South China Agricultural University campus/IP entitlement. If no authorized PDF link is exposed, return `access_required`. Do not store a campus account.

### Direct official sources

Use the generic adapter only when the publisher page exposes unique citation metadata, one official PDF, and one official BibTeX link on approved hosts. Ambiguity is a page-contract failure.

## Page drift

For a named phase failure, save only the minimal non-sensitive page structure needed for a fixture. Prefer stable metadata, hrefs, data attributes, and exact accessible names. Change the narrow contract and its test together. Never broaden an authentication host while repairing a selector.
