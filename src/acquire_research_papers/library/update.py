from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import time
from pathlib import Path
from typing import Any

from acquire_research_papers.models import normalize_doi

from .audit import audit_library, pdf_evidence, read_bib, scan_library, write_csv
from .metadata import digest, write_json
from .plans import save_plan


def update_library(directory: Path | str, *, output: Path | str, application: Any = None,
                   metadata: dict | None = None, client: Any = None,
                   verify_only: bool = False, watch: Path | str | None = None,
                   timeout: float = 0, poll_interval: float = 1.0) -> dict:
    """Stage official replacements and a reviewable plan; never apply automatically.

    A watch directory supplies user-downloaded pairs, not browser automation. A single
    consolidated queue is rewritten when watched pairs satisfy pending DOI identities.
    """
    if not math.isfinite(timeout) or not 0 <= timeout <= 300:
        raise ValueError("watch timeout must be between 0 and 300 seconds")
    if not math.isfinite(poll_interval) or not 0.1 <= poll_interval <= 30:
        raise ValueError("watch poll interval must be between 0.1 and 30 seconds")
    if watch is not None and not Path(watch).is_dir():
        raise ValueError("watch directory does not exist")
    baseline = {}
    if watch is not None:
        for entry in scan_library(Path(watch))["items"]:
            for suffix in ("pdf", "bib"):
                if entry.get(suffix):
                    baseline[entry[suffix]] = entry[suffix + "_sha256"]
    output = Path(output).resolve()
    root = Path(directory).resolve()
    if output == root or root in output.parents:
        raise ValueError("update staging output must be outside the library")
    report = audit_library(root, metadata=metadata, client=client, output=output)
    if verify_only:
        result = {"status": "verified", "audit": str(output / "audit.json"), "items": report["items"]}
        write_json(output / "update.json", result)
        return result
    candidates = [item for item in report["items"] if item.get("doi") and item["status"] != "ambiguous" and (
        item.get("publication_status") in {"outdated", "possible_update"}
        or item["status"] in {"missing_pdf", "missing_bib", "invalid_pdf"})]
    official_by_doi = {item["doi"]: item.get("official", {}) for item in candidates}

    def stage_provenance(pair: dict, doi: str, destination: Path) -> dict:
        """Keep native source records byte-for-byte; absent proof remains a manual import."""
        proof_path = pair.get("provenance")
        if proof_path:
            raw = Path(proof_path).read_bytes()
            proof = json.loads(raw.decode("utf-8-sig"))
            if (not isinstance(proof, dict)
                    or normalize_doi(proof.get("metadata", {}).get("doi")) != doi
                    or proof.get("pdf_sha256") != digest(Path(pair["pdf"]))
                    or proof.get("bibtex_sha256") != digest(Path(pair["bib"]))):
                raise ValueError("replacement provenance does not match the staged pair")
        else:
            raw = (json.dumps({"metadata": {"doi": doi},
                               "pdf_sha256": digest(Path(pair["pdf"])),
                               "bibtex_sha256": digest(Path(pair["bib"])),
                               "bibtex_source": "manual_import",
                               "kind": "user_supplied_pair"}, indent=2) + "\n").encode("utf-8")
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / "update.provenance.json"
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError("staged provenance collision")
        else:
            target.write_bytes(raw)
        return {**pair, "provenance": str(target)}

    def validate_replacement(pdf: Path, bib: Path, doi: str) -> None:
        fields, _ = read_bib(bib)
        if fields["doi"] != doi:
            raise ValueError("replacement citation DOI mismatch")
        evidence = pdf_evidence(pdf)
        def title_key(value):
            return re.sub(r"\W", "", str(value)).casefold()
        if (evidence.get("error") or (evidence["dois"] and evidence["dois"] != [doi])
                or (not evidence["dois"] and title_key(evidence.get("title")) != title_key(fields.get("title")))):
            raise ValueError("replacement PDF identity requires verification")
        official = official_by_doi.get(doi, {})
        if official.get("title") and title_key(fields.get("title")) != title_key(official["title"]):
            raise ValueError("replacement citation title mismatch")
        final = bool(official.get("issue_date") and official.get("volume")
                     and (official.get("pages") or official.get("article_number")))
        if final:
            if evidence.get("early_access"):
                raise ValueError("replacement PDF is still Early Access")
            for field in ("volume", "pages", "article_number"):
                if official.get(field) and title_key(fields.get(field)) != title_key(official[field]):
                    raise ValueError("replacement citation has stale or missing issue placement")
    items, staged = [], {}
    for item in candidates:
        doi = item["doi"]
        row = {"doi": doi, "status": "manual_required", "reason": "official_pair_required"}
        if doi in staged:
            row["status"] = "staged"
        elif application is not None:
            destination = output / "staged" / hashlib.sha256(doi.encode()).hexdigest()[:16]
            try:
                delivered = application.fetch(doi, destination)
                pdf = getattr(delivered, "pdf", None)
                bib = getattr(delivered, "bibtex", None)
                if pdf is not None and bib is not None:
                    validate_replacement(Path(pdf), Path(bib), doi)
                    pair = {"pdf": str(Path(pdf).resolve()), "bib": str(Path(bib).resolve())}
                    if getattr(delivered, "provenance", None):
                        pair["provenance"] = str(delivered.provenance)
                else:
                    found = [i for i in scan_library(destination)["items"]
                             if i["status"] == "paired" and i.get("doi") == doi]
                    if len(found) != 1:
                        raise ValueError("fetch did not produce exactly one official pair")
                    validate_replacement(Path(found[0]["pdf"]), Path(found[0]["bib"]), doi)
                    pair = found[0]
                staged[doi] = stage_provenance(pair, doi, destination)
                row["status"] = "staged"
            except Exception as exc:
                row["reason"] = type(exc).__name__
        items.append(row)

    def queue() -> None:
        write_csv(output / "manual-download.csv", [row for row in items if row["status"] != "staged"],
                  ["doi", "status", "reason"])

    queue()
    deadline = time.monotonic() + timeout
    previous_hashes: dict[str, tuple[str, str]] = {}
    while watch is not None and any(row["status"] != "staged" for row in items):
        found = scan_library(Path(watch))["items"]
        matches = {}
        for entry in found:
            if entry["status"] == "paired":
                matches.setdefault(entry["doi"], []).append(entry)
        for row in items:
            if row["status"] == "staged" or len(matches.get(row["doi"], [])) != 1:
                continue
            entry = matches[row["doi"]][0]
            hashes = (entry["pdf_sha256"], entry["bib_sha256"])
            if all(baseline.get(entry[suffix]) == entry[suffix + "_sha256"] for suffix in ("pdf", "bib")):
                row["reason"] = "preexisting_download_use_explicit_import"
                continue
            # Require two consecutive stable observations before staging user downloads.
            if previous_hashes.get(row["doi"]) == hashes:
                try:
                    validate_replacement(Path(entry["pdf"]), Path(entry["bib"]), row["doi"])
                except ValueError:
                    row["reason"] = "download_identity_or_version_requires_verification"
                    continue
                destination = output / "staged" / hashlib.sha256(row["doi"].encode()).hexdigest()[:16]
                destination.mkdir(parents=True, exist_ok=True)
                pair = {}
                for suffix in ("pdf", "bib"):
                    target = destination / ("manual." + suffix)
                    source = Path(entry[suffix])
                    if target.exists() and digest(target) != entry[suffix + "_sha256"]:
                        raise ValueError("manual staging collision")
                    if not target.exists():
                        with source.open("rb") as incoming, target.open("xb") as outgoing:
                            shutil.copyfileobj(incoming, outgoing)
                    if digest(target) != entry[suffix + "_sha256"]:
                        raise ValueError("manual download changed while staging")
                    pair[suffix] = str(target)
                if entry.get("provenance"):
                    pair["provenance"] = entry["provenance"]
                staged[row["doi"]] = stage_provenance(pair, row["doi"], destination)
                row.update(status="staged", reason="user_downloaded_pair")
            previous_hashes[row["doi"]] = hashes
        queue()
        if time.monotonic() >= deadline:
            break
        time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
    actions = []
    for item in candidates:
        if item["doi"] not in staged:
            continue
        pair = staged[item["doi"]]
        for suffix in ("pdf", "bib", "provenance"):
            source = Path(pair[suffix])
            existing = item.get(suffix)
            other = (item.get("pdf") or item.get("bib") if suffix == "provenance"
                     else item.get("bib" if suffix == "pdf" else "pdf"))
            extension = ".provenance.json" if suffix == "provenance" else "." + suffix
            target = Path(existing) if existing else Path(other).with_suffix(extension)
            action = {"operation": "replace" if target.exists() else "copy",
                      "source": str(source), "target": str(target), "sha256": digest(source),
                      "doi": item["doi"]}
            if target.exists():
                action["target_sha256"] = digest(target)
            actions.append(action)
    plan = output / "plan.json"
    save_plan(actions, source_root=output / "staged", target_root=root,
              output=plan, mode="update")
    result = {"status": "staged" if staged else "manual_required" if items else "no_updates",
              "items": items, "plan": str(plan), "manual_queue": str(output / "manual-download.csv")}
    write_json(output / "update.json", result)
    return result
