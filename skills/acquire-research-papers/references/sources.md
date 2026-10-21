# Sources and venue coverage

Run `arp sources` for the offline inventory or `arp sources --spec <corpus.yaml>` for every requested venue/year slice. This needs no configured credentials or publisher browser. It reuses the live providers' venue/type gates and the Crossref identifier gate. An available capability is not a successful live fetch. Inspect `coverage.jsonl` and `discovery-errors.jsonl` after discovery.

| Source and primary documentation | Role and supported scope | Limit / acceptance evidence |
| --- | --- | --- |
| [ACL Anthology](https://aclanthology.org/) | Official `{year}.acl-long` volume, long papers; exact ACL aliases | Does not enumerate all Anthology venues, workshops, Findings or short papers. Verify requested volume, count, pagination and missing abstracts in the run. |
| [IJCAI proceedings](https://www.ijcai.org/proceedings/) | Official yearly index and main-track details; exact IJCAI aliases | Other tracks are not implied. Check track, year and all listed detail pages. |
| [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | Deposited venue/year metadata; first ISSN, collection DOI via `alternative-id`, otherwise container title | Conference enumeration requires collection DOI or ISSN. All collections must finish pagination. Exact identifiers improve scope but do not prove every paper was deposited. |
| [IEEE Xplore](https://ieeexplore.ieee.org/) | Official PDF/raw BibTeX with institution access | No official venue enumerator. Discovery uses metadata services. One CARSI institution has historical live validation; each additional profile requires its own smoke test. |
| [ACM Digital Library](https://dl.acm.org/) | Conditional official HTTP PDF/raw BibTeX acquisition | No official venue enumerator or production browser adapter. Blocked official endpoints require manual action. |
| [ScienceDirect](https://www.sciencedirect.com/) / [Elsevier APIs](https://dev.elsevier.com/) | Manual official file acquisition; API may resolve expected identity | No automated article-page or organization-login flow. API configuration and subscription entitlement are separate. |
| [OpenAlex API](https://docs.openalex.org/) / [Semantic Scholar API](https://www.semanticscholar.org/product/api) | Optional candidate search, enrichment and bounded citation graph | Configure the needed API independently. Search/ranking/neighbor limits and missing upstream records constrain recall. Never use metadata exports as final publisher BibTeX. |
| [ORCID public API](https://info.orcid.org/documentation/api-tutorials/api-tutorial-read-data-on-a-record/) / [DBLP](https://dblp.org/faq/How+to+use+the+dblp+search+API.html) | Public author works; supplied homepage DOI links and bounded Crossref author search supplement them | Identity ambiguity, truncation and errors remain explicit. No complete-bibliography claim. |

MinerU parses acquired PDFs; it is not a paper discovery source. The internal generic publisher adapter is not a public default adapter.

The priority venue list has not been selected. The table records existing capabilities, not certification of all meetings or journals. For each later priority venue, record its canonical name/aliases, years, tracks/types, official index URL, exact identifiers, expected counts, observed provider completion, sample identity verification and any missing coverage. Declare support only for the tested scope. An unsupported publisher remains `unknown` until its access and artifact contract is validated.

“Complete” in a provider ledger means that source's bounded enumeration finished. It never establishes that every real publication exists upstream. A topic result set, author bibliography, publisher artifact adapter and official venue index answer different questions.
