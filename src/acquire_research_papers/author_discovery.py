"""Bounded public author discovery with explicit identity and source coverage limits."""
from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from acquire_research_papers.http import SafeHttpClient
from acquire_research_papers.models import normalize_doi
from acquire_research_papers.library.audit import DOI, scan_library, write_csv
from acquire_research_papers.library.metadata import (
    OfficialMetadataClient, clean, crossref_record, public_url, write_json,
)


def _date_bounds(value: str) -> tuple[dt.date, dt.date]:
    if not re.fullmatch(r"\d{4}(?:-\d{2})?(?:-\d{2})?", value):
        raise ValueError("dates must use YYYY, YYYY-MM, or YYYY-MM-DD")
    parts = [int(x) for x in value.split("-")]
    try:
        year = parts[0]
        month = parts[1] if len(parts) > 1 else 1
        day = parts[2] if len(parts) > 2 else 1
        start = dt.date(year, month, day)
        last_month = month if len(parts) > 1 else 12
        last_day = day if len(parts) > 2 else calendar.monthrange(year, last_month)[1]
        return start, dt.date(year, last_month, last_day)
    except ValueError as exc:
        raise ValueError("invalid publication date") from exc


def validate_spec(spec: dict) -> dict:
    if not isinstance(spec, dict) or not clean(spec.get("name")):
        raise ValueError("author specification requires a name")
    spec = dict(spec)
    if spec.get("orcid"):
        spec["orcid"] = re.sub(r"^https://orcid\.org/", "", str(spec["orcid"]))
        if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", spec["orcid"]):
            raise ValueError("invalid ORCID identifier")
    if spec.get("dblp"):
        spec["dblp"] = re.sub(r"^https://dblp\.org/pid/", "", str(spec["dblp"])).removesuffix(".html")
        if not re.fullmatch(r"[\w/-]{1,160}", spec["dblp"]) or ".." in spec["dblp"]:
            raise ValueError("invalid DBLP person identifier")
    if spec.get("homepage"):
        public_url(str(spec["homepage"]))
    for name in ("date_from", "date_to"):
        if spec.get(name):
            _date_bounds(str(spec[name]))
    if spec.get("date_from") and spec.get("date_to"):
        if _date_bounds(spec["date_from"])[0] > _date_bounds(spec["date_to"])[1]:
            raise ValueError("author date range is reversed")
    limit = spec.get("max_records", 100)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("max_records must be between 1 and 1000")
    spec["max_records"] = limit
    if spec.get("coauthors") and not isinstance(spec["coauthors"], list):
        raise ValueError("coauthors must be a list")
    return spec


class PublicAuthorClient:
    """Anonymous ORCID, DBLP, homepage DOI links, and Crossref public metadata.

    All requests have a 15-second timeout and no retries. Limits and truncation are
    returned as evidence instead of being hidden behind a completeness claim.
    """

    def __init__(self, *, http_factory: Any = None, metadata_client: Any = None):
        self.http_factory = http_factory
        self.metadata_client = metadata_client or OfficialMetadataClient()

    def _get(self, url: str, *, json_response: bool = True) -> Any:
        public_url(url)
        hostname = urlsplit(url).hostname
        factory = self.http_factory or SafeHttpClient
        client = factory(allowed_hosts={hostname}, timeout=15, retries=0)
        try:
            response = client.get(url, headers={"Accept": "application/json" if json_response else "text/html,application/xml"})
            return response.json() if json_response else response.text
        finally:
            client.close()

    def fetch(self, source: str, spec: dict) -> dict:
        maximum = spec["max_records"]
        if source == "orcid":
            if not spec.get("orcid"):
                return {"records": [], "status": "not_configured", "reason": "ORCID ID not supplied"}
            payload = self._get(f"https://pub.orcid.org/v3.0/{spec['orcid']}/works")
            records = []
            groups = payload.get("group", [])
            for group in groups[:maximum]:
                summaries = group.get("work-summary") or []
                if not summaries:
                    continue
                work = summaries[0]
                external = work.get("external-ids", {}).get("external-id", [])
                doi = next((value.get("external-id-value") for value in external
                            if value.get("external-id-type", "").casefold() == "doi"), None)
                title = work.get("title", {}).get("title", {}).get("value", "")
                date = work.get("publication-date") or {}
                year = (date.get("year") or {}).get("value")
                records.append({"doi": doi, "title": title, "year": year,
                    "publication_date": "-".join(str(date[k]["value"]) for k in ("year", "month", "day")
                                                  if date.get(k) and date[k].get("value")),
                    "type": work.get("type"), "source_id": str(work.get("put-code", "")),
                    "identity_evidence": "ORCID public works record"})
            return {"records": records, "reported_total": len(groups),
                    "truncated": len(groups) > maximum, "status": "ok"}
        if source == "dblp":
            if not spec.get("dblp"):
                return {"records": [], "status": "not_configured", "reason": "DBLP person ID not supplied"}
            xml = self._get("https://dblp.org/pid/" + quote(spec["dblp"], safe="/") + ".xml",
                            json_response=False)
            root = ET.fromstring(xml)
            records = []
            entries = root.findall("r")
            for parent in entries[:maximum]:
                if not len(parent):
                    continue
                entry = parent[0]
                links = [node.text or "" for node in entry.findall("ee")]
                doi = next((link for link in links if "doi.org/" in link), None)
                records.append({"doi": doi, "title": "".join(entry.find("title").itertext())
                    if entry.find("title") is not None else "", "year": entry.findtext("year"),
                    "venue": entry.findtext("journal") or entry.findtext("booktitle"),
                    "authors": [a.text or "" for a in entry.findall("author")],
                    "type": entry.tag, "source_id": entry.get("key"),
                    "identity_evidence": "DBLP person bibliography"})
            return {"records": records, "reported_total": len(entries),
                    "truncated": len(entries) > maximum, "status": "ok"}
        if source == "homepage":
            if not spec.get("homepage"):
                return {"records": [], "status": "not_configured", "reason": "homepage not supplied"}
            text = self._get(spec["homepage"], json_response=False)
            dois = sorted({normalize_doi(value.rstrip(".,;)]")) for value in DOI.findall(text)})
            records, errors = [], []
            for doi in dois[:maximum]:
                try:
                    record = self.metadata_client.lookup(doi)
                    record["identity_evidence"] = "DOI linked on supplied homepage; authorship requires review"
                    records.append(record)
                except Exception as exc:
                    errors.append({"doi": doi, "error": type(exc).__name__})
                    records.append({"doi": doi, "identity_evidence": "homepage DOI link"})
            return {"records": records, "reported_total": len(dois), "errors": errors,
                    "truncated": len(dois) > maximum, "status": "ok"}
        if source == "database":
            query = urlencode({"query.author": spec["name"], "rows": min(maximum, 1000)})
            payload = self._get("https://api.crossref.org/works?" + query)["message"]
            records = [crossref_record(item) for item in payload.get("items", [])]
            return {"records": records, "reported_total": payload.get("total-results"),
                    "truncated": payload.get("total-results", len(records)) > len(records),
                    "status": "ok", "scope": "Crossref name search; results require author identity review"}
        raise ValueError("unknown author discovery source")


def _match_key(value: Any) -> str:
    return " ".join(re.findall(r"\w+", clean(value).casefold()))


def _identity(record: dict, source: str, spec: dict) -> str:
    if (source == "orcid" and spec.get("orcid")) or (source == "dblp" and spec.get("dblp")):
        return "linked_id"
    supplied_orcid = spec.get("orcid", "")
    if supplied_orcid and any(supplied_orcid == str(oid).rsplit("/", 1)[-1]
                             for oid in record.get("author_orcids", [])):
        return "linked_id"
    name = _match_key(spec["name"])
    authors = {_match_key(author) for author in record.get("authors", [])}
    affiliation = _match_key(spec.get("affiliation"))
    coauthors = {_match_key(author) for author in spec.get("coauthors", [])}
    affiliations = [_match_key(value) for author in record.get("author_details", [])
                    if _match_key(author.get("name")) == name
                    for value in author.get("affiliations", [])]
    if name in authors and ((affiliation and any(affiliation in a for a in affiliations))
                            or coauthors.intersection(authors)):
        return "supported"
    return "ambiguous"


def discover_author(spec: dict, *, records: dict | None = None, clients: dict | None = None,
                    output: Path | str | None = None) -> dict:
    spec = validate_spec(spec)
    sources = list(records) if records is not None else ["orcid", "dblp", "homepage", "database"]
    provider = PublicAuthorClient()
    coverage, merged = {}, {}
    for source in sources:
        try:
            if records is not None:
                value = records[source]
                value = {"records": value, "status": "fixture"} if isinstance(value, list) else value
            else:
                selected = (clients or {}).get(source, provider)
                value = selected.fetch(source, spec)
            if not isinstance(value, dict):
                raise ValueError("author source must return records and coverage")
            source_records = value.get("records") or []
            if not isinstance(source_records, list):
                raise ValueError("author source records must be an array")
            coverage[source] = {key: item for key, item in value.items() if key != "records"}
            coverage[source]["fetched"] = min(len(source_records), spec["max_records"])
            if len(source_records) > spec["max_records"]:
                coverage[source]["truncated"] = True
            for index, raw in enumerate(source_records[:spec["max_records"]]):
                record = dict(raw)
                doi = normalize_doi(record.get("doi") or record.get("DOI"))
                if doi and not re.fullmatch(r"10\.\d{4,9}/\S+", doi):
                    doi = None
                key = doi or f"{source}:{record.get('source_id', index)}"
                identity = _identity(record, source, spec)
                if key not in merged:
                    merged[key] = {"doi": doi, "title": clean(record.get("title")),
                                   "sources": [], "evidence": [], "identity_status": identity}
                current = merged[key]
                current["sources"].append(source) if source not in current["sources"] else None
                current["evidence"].append({"source": source, "identity_status": identity,
                                            "record": record})
                if identity in {"linked_id", "supported"}:
                    current["identity_status"] = identity
                for field in ("title", "issue_date", "online_date", "publication_date", "year", "venue",
                              "type", "authors", "url", "volume", "issue", "pages", "is_preprint_of", "relations"):
                    if not current.get(field) and record.get(field):
                        current[field] = record[field]
                current.setdefault("conflicts", [])
                for field in ("issue_date", "online_date"):
                    if current.get(field) and record.get(field) and current[field] != record[field]:
                        current["conflicts"].append({"field": field, "values": [current[field], record[field]]})
        except Exception as exc:
            coverage[source] = {"status": "failed", "error": type(exc).__name__, "fetched": 0}
    local = {}
    if spec.get("local_dir"):
        for item in scan_library(spec["local_dir"])["items"]:
            if item.get("doi"):
                status = "paired" if item["status"] == "paired" else "bib_only" if item.get("bib") else "pdf_only"
                local.setdefault(item["doi"], status)
    papers, excluded = [], 0
    lower = _date_bounds(str(spec["date_from"]))[0] if spec.get("date_from") else dt.date.min
    upper = _date_bounds(str(spec["date_to"]))[1] if spec.get("date_to") else dt.date.max
    for paper in merged.values():
        stage = clean(paper.get("type")).casefold()
        paper["publication_stage"] = ("preprint" if stage in {"preprint", "posted-content", "posted_content"}
                                      else "formal" if paper.get("issue_date")
                                      else "early_access" if paper.get("online_date")
                                      else "unknown")
        version_of = paper.get("is_preprint_of")
        if not version_of:
            for relation in (paper.get("relations") or {}).get("is-preprint-of", []):
                if relation.get("id-type") == "doi":
                    version_of = relation.get("id")
                    break
        paper["version_of"] = normalize_doi(version_of)
        paper["count_as_formal"] = (paper["publication_stage"] == "formal" and
                                     paper["identity_status"] != "ambiguous")
        basis = next((field for field in ("issue_date", "online_date", "publication_date", "year")
                      if paper.get(field)), None)
        paper["date_basis"] = basis or "unknown"
        date = str(paper.get(basis, "")) if basis else ""
        try:
            start, end = _date_bounds(date)
            if end < lower or start > upper:
                alternatives = [str(v) for conflict in paper.get("conflicts", [])
                                if conflict["field"] == basis for v in conflict["values"]]
                overlap = False
                for value in alternatives:
                    try:
                        left, right = _date_bounds(value)
                        overlap = overlap or not (right < lower or left > upper)
                    except ValueError:
                        overlap = True
                if not overlap:
                    excluded += 1
                    continue
                paper["date_scope"] = "conflict_requires_review"
            else:
                paper["date_scope"] = "in_range" if start >= lower and end <= upper else "overlaps_range"
        except ValueError:
            paper["date_scope"] = "unknown"
        paper["local_status"] = local.get(paper["doi"], "missing")
        papers.append(paper)
    papers.sort(key=lambda paper: (str(paper.get("doi") or ""), clean(paper.get("title"))))
    result = {"schema_version": 1, "spec": spec,
              "identity": {"name": clean(spec["name"]), "status": "identified" if spec.get("orcid") or spec.get("dblp")
                           else "ambiguous", "orcid": spec.get("orcid"), "dblp": spec.get("dblp")},
              "papers": papers,
              "groups": {group: [p.get("doi") or p.get("title") for p in papers
                                   if p["publication_stage"] == stage]
                         for group, stage in (("formal", "formal"), ("early_access", "early_access"),
                                              ("preprints", "preprint"), ("unknown", "unknown"))},
              "coverage": {"complete": False, "sources": coverage,
                  "excluded_by_date": excluded,
                  "limitations": ["Public sources have incomplete coverage and may contain author identity errors.",
                      "Issue publication date is primary; online publication and preprints remain separate evidence.",
                      "Name-only, homepage, and database matches require identity review."]}}
    # A stable digest identifies this discovery run without touching corpus/research state.
    result["sha256"] = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if output is not None:
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / "author-discovery.json", result)
        write_csv(output / "author-discovery.csv", papers,
            ["doi", "title", "identity_status", "issue_date", "online_date", "date_basis", "publication_stage", "local_status"])
        lines = ["# Author discovery", "", clean(spec["name"]), "", f"Candidate works: {len(papers)}", "",
                 "Coverage is incomplete. Review identity evidence and source errors in author-discovery.json.", ""]
        lines.extend(f"- {clean(paper.get('title') or paper.get('doi'))}: {paper['identity_status']}"
                     for paper in papers)
        (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
