from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from acquire_research_papers.bibliography import decode_bibtex_bytes, parse_bibtex
from acquire_research_papers.models import normalize_doi
from .metadata import OfficialMetadataClient, clean, compare_publication, digest, read_json, write_json

DOI = re.compile(r"10\.\d{4,9}/[^\s<>\"{}]+", re.IGNORECASE)
IGNORED_DIRS = {".arp-backups", ".arp-staging", ".git", "__pycache__"}


def files(root: Path, suffix: str):
    for path in sorted(root.rglob("*"), key=lambda p: str(p).casefold()):
        if (path.is_file() and not path.is_symlink() and path.suffix.casefold() == suffix
                and not IGNORED_DIRS.intersection(path.relative_to(root).parts)):
            yield path


def read_bib(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    text, encoding = decode_bibtex_bytes(raw)
    parsed = parse_bibtex(text)
    fields = dict(parsed.fields)
    fields["doi"] = normalize_doi(fields.get("doi"))
    fields["title"] = re.sub(r"[{}]", "", fields.get("title", ""))
    fields["venue"] = fields.get("journal") or fields.get("booktitle") or ""
    fields["entry_type"] = parsed.entry_type
    fields["authors"] = list(parsed.author_surnames)
    # Ordinary BibTeX year/month do not establish whether a date is online or issue publication.
    fields["issue_date"] = fields.get("issue_date") or fields.get("date")
    return fields, encoding


def pdf_evidence(path: Path) -> dict:
    try:
        reader = PdfReader(path)
        metadata = reader.metadata or {}
        fragments = [str(value) for value in metadata.values()]
        for page in reader.pages[:2]:
            fragments.append(page.extract_text() or "")
        found = sorted({normalize_doi(match.rstrip(".,;)]"))
                        for match in DOI.findall("\n".join(fragments))})
        early = bool(re.search(r"\bearly\s+access\b|\barticle\s+in\s+press\b|\baccepted\s+manuscript\b",
                               "\n".join(fragments), re.IGNORECASE))
        return {"dois": found, "pages": len(reader.pages),
                "title": clean(metadata.get("/Title", "")), "early_access": early}
    except Exception as exc:
        return {"dois": [], "error": type(exc).__name__}


def scan_library(directory: Path | str) -> dict:
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError("library directory does not exist")
    pdfs = list(files(root, ".pdf"))
    pdf_by_stem: dict[str, list[Path]] = defaultdict(list)
    for path in pdfs:
        pdf_by_stem[str(path.with_suffix("")).casefold()].append(path)
    evidence = {str(path): pdf_evidence(path) for path in pdfs}
    pdf_hashes = {str(path): digest(path) for path in pdfs}
    items = []
    used = set()
    for bib in files(root, ".bib"):
        item: dict[str, Any] = {"bib": str(bib), "bib_sha256": digest(bib), "pdf": None,
                                "doi": None, "status": "ambiguous", "citation_source": "manual_import"}
        try:
            fields, encoding = read_bib(bib)
            item.update(local=fields, doi=fields["doi"], encoding=encoding)
        except Exception as exc:
            item["diagnostic"] = clean(str(exc))
            items.append(item)
            continue
        candidates = pdf_by_stem.get(str(bib.with_suffix("")).casefold(), [])
        pairing = "filename"
        for provenance in sorted(bib.parent.glob("*provenance.json")):
                try:
                    proof = read_json(provenance)
                    if (proof.get("bibtex_sha256") != item["bib_sha256"]
                            or normalize_doi(proof.get("metadata", {}).get("doi")) != item["doi"]):
                        continue
                    proven = [p for p in pdfs if p.parent == bib.parent
                                  and pdf_hashes[str(p)] == proof.get("pdf_sha256")]
                    if proven:
                        candidates = proven
                        pairing = "hash_bound_provenance"
                        item["provenance"] = str(provenance)
                        item["citation_source"] = proof.get("bibtex_source", "manual_import")
                        break
                except (OSError, ValueError, AttributeError):
                    continue
        if not candidates and item["doi"]:
            candidates = [p for p in pdfs if evidence[str(p)]["dois"] == [item["doi"]]]
            pairing = "exact_pdf_doi"
        if len(candidates) > 1:
            item["diagnostic"] = "multiple PDFs match the citation"
        elif not candidates:
            item["status"] = "missing_pdf"
        else:
            pdf = candidates[0]
            item.update(pdf=str(pdf), pdf_sha256=pdf_hashes[str(pdf)], pdf_evidence=evidence[str(pdf)],
                        pairing_evidence=pairing)
            used.add(str(pdf))
            identifiers = evidence[str(pdf)]["dois"]
            if evidence[str(pdf)].get("error"):
                item["status"] = "invalid_pdf"
            elif identifiers and item["doi"] and item["doi"] not in identifiers:
                item.update(status="ambiguous", diagnostic="PDF and BibTeX DOI conflict")
            elif len(identifiers) > 1 and pairing != "hash_bound_provenance":
                item.update(status="ambiguous", diagnostic="multiple PDF DOI identities require confirmation")
            elif not item["doi"]:
                item.update(status="ambiguous", diagnostic="citation has no stable DOI identity")
            elif (not identifiers and pairing != "hash_bound_provenance"
                  and re.sub(r"\W", "", evidence[str(pdf)].get("title", "")).casefold()
                  != re.sub(r"\W", "", fields.get("title", "")).casefold()):
                item.update(status="ambiguous", diagnostic="PDF identity requires confirmation; filename alone is insufficient")
            else:
                item["status"] = "paired"
                item["identity_confidence"] = "pdf_doi" if identifiers else "citation_and_filename"
            page_range = re.fullmatch(r"(\d+)\s*[-–]+\s*(\d+)", str(fields.get("pages", "")))
            if (fields.get("entry_type") in {"incollection", "inproceedings"} and page_range
                    and evidence[str(pdf)].get("pages", 0) > max(50, int(page_range[2]) - int(page_range[1]) + 6)):
                item.update(status="ambiguous", diagnostic="possible complete proceedings; chapter identity and boundaries required")
        items.append(item)
    for pdf in pdfs:
        if str(pdf) not in used:
            identifiers = evidence[str(pdf)]["dois"]
            items.append({"pdf": str(pdf), "pdf_sha256": pdf_hashes[str(pdf)], "bib": None,
                          "doi": identifiers[0] if len(identifiers) == 1 else None,
                          "pdf_evidence": evidence[str(pdf)], "status": "missing_bib"})
    by_pdf: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        if item.get("pdf") and item.get("bib"):
            by_pdf[item["pdf"]].append(item)
    for group in by_pdf.values():
        if len(group) > 1:
            for item in group:
                item.update(status="ambiguous", diagnostic="multiple citations share the same PDF")
    by_doi: dict[str, list[dict]] = defaultdict(list)
    by_hash: dict[str, list[str]] = defaultdict(list)
    for item in items:
        if item["doi"]:
            by_doi[item["doi"]].append(item)
        for suffix in ("pdf", "bib"):
            if item.get(suffix + "_sha256"):
                by_hash[item[suffix + "_sha256"]].append(item[suffix])
    duplicates = {doi: [i.get("bib") for i in group]
                  for doi, group in by_doi.items() if len(group) > 1}
    return {"schema_version": 1, "root": str(root), "items": items,
            "duplicates": {"doi": duplicates, "bytes": {h: sorted(set(paths))
                for h, paths in by_hash.items() if len(set(paths)) > 1}},
            "summary": {"pairs": sum(i["status"] == "paired" for i in items),
                        "items": len(items), "duplicate_dois": len(duplicates),
                        "ambiguous": sum(i["status"] == "ambiguous" for i in items)}}


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        # CSV is intended for review in spreadsheets; neutralize formulas in untrusted titles/URLs.
        safe = {key: ("'" + str(value) if str(value).startswith(("=", "+", "-", "@"))
                      else value) for key, value in row.items()}
        writer.writerow(safe)
    path.write_text(stream.getvalue(), encoding="utf-8-sig", newline="")


def write_audit(report: dict, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "audit.json", report)
    columns = ["doi", "status", "publication_status", "pdf", "bib", "diagnostic"]
    write_csv(output / "audit.csv", report["items"], columns)
    queue = [{"doi": i.get("doi"), "url": i.get("official", {}).get("url", ""),
              "reason": i.get("diagnostic") or i["status"], "pdf": i.get("pdf"),
              "bib": i.get("bib")} for i in report["items"]
             if i["status"] != "paired" or i.get("publication_status") in {"outdated", "possible_update"}]
    write_csv(output / "manual-download.csv", queue, ["doi", "url", "reason", "pdf", "bib"])
    lines = ["# Library audit", "", f"Items: {report['summary']['items']}; "
             f"pairs: {report['summary']['pairs']}; duplicate DOIs: "
             f"{report['summary']['duplicate_dois']}", "",
             "Publication status is unknown when authoritative evidence is incomplete.", ""]
    for item in report["items"]:
        name = clean(item.get("doi") or Path(item.get("bib") or item.get("pdf")).name)
        lines.append(f"- {name}: {item['status']}; publication {item.get('publication_status', 'unknown')}")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_library(directory: Path | str, *, metadata: dict | None = None,
                  client: Any = None, output: Path | str | None = None) -> dict:
    report = scan_library(directory)
    metadata = ({normalize_doi(k): v for k, v in metadata.items()}
                if metadata is not None else None)
    provider = client or OfficialMetadataClient()
    cache = {}
    for item in report["items"]:
        doi = item.get("doi")
        official = None
        if doi:
            if doi not in cache:
                try:
                    value = metadata.get(doi) if metadata is not None else provider.lookup(doi)
                    if value and normalize_doi(value.get("doi", doi)) != doi:
                        raise ValueError("official metadata DOI mismatch")
                    cache[doi] = (value, None)
                except Exception as exc:
                    # Do not leak request headers, tokens, or URLs through exception messages.
                    cache[doi] = (None, type(exc).__name__)
            official, error = cache[doi]
            if error:
                item["metadata_error"] = error
        item["official"] = official or {}
        item["citation_status"], item["changes"] = compare_publication(item.get("local", {}), official)
        item["publication_status"] = item["citation_status"]
        evidence = item.get("pdf_evidence", {})
        pdf_version = "early_access" if evidence.get("early_access") else "requires_verification"
        if (official and official.get("pdf_sha256") and item.get("pdf_sha256")
                == official["pdf_sha256"] and official.get("evidence_kind") != "discovery_registry"):
            pdf_version = "publisher_bytes_match"
        item["local_version"] = {"pdf": pdf_version, "citation": item.get("local", {}),
                                 "metadata_verification": "publisher_metadata" if official and
                                 official.get("evidence_kind") == "publisher_metadata" else "metadata_only"}
        final = bool(official and official.get("issue_date") and official.get("volume")
                     and (official.get("pages") or official.get("article_number")))
        if evidence.get("early_access") and final:
            item["publication_status"] = ("possible_update" if official.get("evidence_kind")
                                           == "discovery_registry" else "outdated")
            item["changes"].append({"field": "pdf_version", "local": "early_access",
                                    "official": "issue_assigned"})
        elif item["publication_status"] == "current" and pdf_version != "publisher_bytes_match":
            item["publication_status"] = "unknown"
    if output is not None:
        write_audit(report, Path(output))
    return report
