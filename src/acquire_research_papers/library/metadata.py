"""Read-only publication evidence; missing fields never imply a final publication."""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from bs4 import BeautifulSoup

from acquire_research_papers.http import SafeHttpClient
from acquire_research_papers.models import normalize_doi


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def clean(value: Any, limit: int = 4000) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", html.unescape(str(value or "")))[:limit].strip()


def public_url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password):
        raise ValueError("expected a public HTTP(S) URL without credentials")
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise ValueError("private homepage addresses are not supported")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise ValueError("private homepage addresses are not supported")
    return value


def read_json(path: Path | str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read JSON input: {Path(path).name}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def date_parts(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts", [[]])[0]
    if not parts:
        return None
    return "-".join(str(part) if index == 0 else f"{int(part):02}" for index, part in enumerate(parts))


def crossref_record(record: dict) -> dict:
    titles = record.get("title") or []
    venues = record.get("container-title") or []
    return {
        "doi": normalize_doi(record.get("DOI")),
        "title": clean(titles[0] if titles else ""),
        "venue": clean(venues[0] if venues else ""),
        "venue_abbreviation": clean((record.get("short-container-title") or [""])[0]),
        "issue_date": date_parts(record.get("published-print")),
        "online_date": date_parts(record.get("published-online")),
        "publication_date": date_parts(record.get("published")),
        "volume": clean(record.get("volume")), "issue": clean(record.get("issue")),
        "pages": clean(record.get("page")), "article_number": clean(record.get("article-number")),
        "type": clean(record.get("type")),
        "url": clean((record.get("resource") or {}).get("primary", {}).get("URL") or record.get("URL")),
        "authors": [clean(" ".join(filter(None, (a.get("given"), a.get("family")))))
                    for a in record.get("author", [])],
        "author_details": [{"name": clean(" ".join(filter(None, (a.get("given"), a.get("family"))))),
                            "affiliations": [clean(aff.get("name")) for aff in a.get("affiliation", [])],
                            "orcid": clean(a.get("ORCID"))}
                           for a in record.get("author", [])],
        "affiliations": [clean(aff.get("name")) for a in record.get("author", [])
                         for aff in a.get("affiliation", [])],
        "author_orcids": [clean(a.get("ORCID")) for a in record.get("author", [])
                          if a.get("ORCID")],
        "relations": record.get("relation") or {},
        "source": "Crossref publisher-deposited metadata",
        "evidence_kind": "discovery_registry",
    }


def _publisher_date(value: Any) -> str | None:
    value = clean(value)
    if re.fullmatch(r"\d{4}(?:[-/]\d{1,2})?(?:[-/]\d{1,2})?", value):
        parts = value.replace("/", "-").split("-")
        return "-".join(part if i == 0 else part.zfill(2) for i, part in enumerate(parts))
    for form, output in (("%d %B %Y", "%Y-%m-%d"), ("%d %b %Y", "%Y-%m-%d"),
                         ("%B %Y", "%Y-%m"), ("%b %Y", "%Y-%m")):
        try:
            return datetime.strptime(value, form).strftime(output)
        except ValueError:
            continue
    return None


PUBLISHER_HOSTS = {"ieeexplore.ieee.org", "www.sciencedirect.com", "linkinghub.elsevier.com",
                   "dl.acm.org", "link.springer.com", "onlinelibrary.wiley.com"}


def parse_publisher_metadata(page: str, url: str, doi: str) -> dict:
    """Parse publisher-owned public article evidence without inferring artifact provenance."""
    host = urlsplit(url).hostname
    if host not in PUBLISHER_HOSTS:
        raise ValueError("publisher metadata host is not supported")
    soup = BeautifulSoup(page, "html.parser")
    tags = {str(tag.get("name") or tag.get("property") or "").casefold(): tag.get("content", "")
            for tag in soup.find_all("meta")}
    ieee = {}
    if host == "ieeexplore.ieee.org":
        marker = re.search(r"(?:xplGlobal\.document\.metadata|global\.document\.metadata)\s*=\s*", page)
        if marker:
            try:
                ieee, _ = json.JSONDecoder().raw_decode(page[marker.end():])
            except ValueError:
                ieee = {}
    identity = normalize_doi(ieee.get("doi") or tags.get("citation_doi") or tags.get("dc.identifier"))
    if not identity or identity != normalize_doi(doi):
        raise ValueError("public publisher page has no matching DOI identity")
    first = ieee.get("startPage") or tags.get("citation_firstpage")
    last = ieee.get("endPage") or tags.get("citation_lastpage")
    pages = str(first) + ("-" + str(last) if last and last != first else "") if first else ""
    return {"doi": identity, "title": clean(ieee.get("title") or tags.get("citation_title")),
            "venue": clean(ieee.get("publicationTitle") or tags.get("citation_journal_title")
                           or tags.get("citation_conference_title")),
            "volume": clean(ieee.get("volume") or tags.get("citation_volume")),
            "issue": clean(ieee.get("issue") or tags.get("citation_issue")), "pages": pages,
            "article_number": clean(tags.get("citation_article_number")),
            "issue_date": _publisher_date(ieee.get("publicationDate") or tags.get("citation_issue_date")),
            "online_date": _publisher_date(ieee.get("dateOfPublication") or tags.get("citation_online_date")),
            "publication_date": _publisher_date(tags.get("citation_publication_date") or tags.get("citation_date")),
            "source": f"Public publisher metadata ({host})", "evidence_kind": "publisher_metadata",
            "url": url, "artifact_version_verified": False}


class OfficialMetadataClient:
    """Publisher public metadata where accessible; DOI-registry discovery fallback is explicit."""

    def __init__(self, *, http: Any = None, timeout: float = 15.0,
                 publisher_http_factory: Any = None):
        self.http = http
        self.timeout = min(max(float(timeout), 1.0), 60.0)
        self.publisher_http_factory = publisher_http_factory

    def lookup(self, doi: str) -> dict:
        owned = self.http is None
        client = self.http or SafeHttpClient(
            allowed_hosts={"api.crossref.org"}, timeout=self.timeout, retries=0)
        try:
            response = client.get("https://api.crossref.org/works/" + quote(doi, safe=""))
            data = response.json()
            record = crossref_record(data["message"])
            if record["doi"] != normalize_doi(doi):
                raise ValueError("official metadata DOI mismatch")
            url = record.get("url") or ""
            host = urlsplit(url).hostname
            if host in PUBLISHER_HOSTS - {"www.sciencedirect.com", "linkinghub.elsevier.com"}:
                publisher = None
                try:
                    public_url(url)
                    factory = self.publisher_http_factory or SafeHttpClient
                    publisher = factory(allowed_hosts={host}, timeout=self.timeout, retries=0)
                    page = publisher.get(url)
                    public = parse_publisher_metadata(page.text, url, doi)
                    public["discovery_evidence"] = record
                    return public
                except Exception as exc:
                    record["publisher_lookup_error"] = type(exc).__name__
                finally:
                    if publisher:
                        publisher.close()
            return record
        finally:
            if owned:
                client.close()


def compare_publication(local: dict, official: dict | None) -> tuple[str, list[dict]]:
    if not official:
        return "unknown", []
    changes = []
    for field in ("volume", "issue", "pages", "issue_date", "online_date"):
        old, new = local.get(field), official.get(field)
        if old and new and str(old) != str(new):
            changes.append({"field": field, "local": old, "official": new})
    issue_year = str(official.get("issue_date") or "")[:4]
    if issue_year and local.get("year") and issue_year != str(local["year"]):
        changes.append({"field": "year", "local": local["year"], "official": issue_year})
    # Finalization requires positive placement evidence; an absent early-access flag says nothing.
    final = bool(official.get("issue_date") and official.get("volume")
                 and (official.get("pages") or official.get("article_number")))
    local_final = bool(local.get("volume") and (local.get("pages") or local.get("article_number")))
    if final and not local_final:
        changes.append({"field": "publication_stage", "local": "early_access_or_incomplete",
                        "official": "issue_assigned"})
    if changes:
        return ("possible_update" if official.get("evidence_kind") == "discovery_registry"
                else "outdated"), changes
    required = ("volume", "pages", "issue_date")
    if (official.get("evidence_kind") != "discovery_registry" and final and local_final
            and all(local.get(k) and official.get(k) for k in required)):
        return "current", []
    return "unknown", []
