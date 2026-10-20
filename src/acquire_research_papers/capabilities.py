"""Independent deterministic capabilities, shared by every agent host and recipe."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

from acquire_research_papers.acquisition.base import SourceDocument
from acquire_research_papers.acquisition.manual_handoff import validate_manual_pair
from acquire_research_papers.contracts import validate_contract
from acquire_research_papers.artifacts import sanitize_artifact_value
from acquire_research_papers.discovery.contracts import CandidateMetadata, DiscoveryRequest
from acquire_research_papers.discovery.coordinator import DiscoveryCoordinator
from acquire_research_papers.models import PaperMetadata, normalize_doi
from acquire_research_papers.run_context import artifact_reference, content_hash
from acquire_research_papers.selection import SelectionStore, build_selection_records


@dataclass(frozen=True)
class OperationResult:
    status: str = "complete"
    completed: int = 0
    pending: int = 0
    diagnostics: tuple[dict, ...] = ()
    next_actions: tuple[dict, ...] = ()
    outputs: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        result = asdict(self)
        validate_contract(result, "operation-result.schema.json")
        return result


def resolve_identity(record: Mapping | str) -> dict:
    value = dict(record) if isinstance(record, Mapping) else (
        {"official_url": record} if str(record).startswith(("http://", "https://"))
        else {"doi": record})
    dois = set()
    source_ids = value.get("source_ids", {})
    if not isinstance(source_ids, Mapping):
        raise ValueError("identity source_ids must be an object")
    for supplied in (value.get("doi"), source_ids.get("doi")):
        if supplied:
            doi = normalize_doi(str(supplied))
            if not re.fullmatch(r"10\.\d{4,9}/\S+", doi or ""):
                raise ValueError("invalid DOI identity")
            dois.add(doi)
    official = value.get("official_url") or value.get("landing_url")
    if official:
        url = urlsplit(str(official))
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("identity URL must be HTTP(S) without credentials")
        if url.hostname.casefold() in {"doi.org", "dx.doi.org"}:
            doi = normalize_doi(str(official))
            if not re.fullmatch(r"10\.\d{4,9}/\S+", doi or ""):
                raise ValueError("invalid DOI URL identity")
            dois.add(doi)
            official = None
        else:
            official = urlunsplit((url.scheme.casefold(), url.netloc.casefold(),
                                  url.path.rstrip("/"), url.query, ""))
            official = sanitize_artifact_value(official)
    ambiguous = len(dois) > 1
    doi = next(iter(dois)) if len(dois) == 1 else None
    identity = f"doi:{doi}" if doi else f"url:{official}" if official and not ambiguous else None
    result = {"schema_version": 1, "status": "ambiguous" if ambiguous else
            "resolved" if identity else "unresolved", "identity": identity, "doi": doi,
            "official_url": official, "source_ids": dict(source_ids),
            "conflicts": [{"field": "doi", "values": sorted(dois)}] if ambiguous else []}
    validate_contract(result, "identity.schema.json")
    return result


def merge_collection(records: Sequence[dict]) -> dict:
    merged: dict[str, dict] = {}
    unresolved, conflicts = [], []
    for record in records:
        identity = resolve_identity(record)
        key = identity["identity"]
        if not key:
            unresolved.append(record)
            continue
        if key not in merged:
            merged[key] = dict(record)
            continue
        target = merged[key]
        for field, value in record.items():
            old = target.get(field)
            if old in (None, "", [], ()):
                target[field] = value
            elif value not in (None, "", [], ()) and value != old:
                conflicts.append({"identity": key, "field": field, "values": [old, value]})
    return {"records": list(merged.values()), "unresolved": unresolved, "conflicts": conflicts}


def compare_collections(left: Sequence[dict], right: Sequence[dict]) -> dict:
    def indexed(records):
        return {item["identity"]: record for record in records
                if (item := resolve_identity(record))["identity"]}
    a, b = indexed(left), indexed(right)
    only_a, only_b = sorted(a.keys() - b.keys()), sorted(b.keys() - a.keys())
    hints = [{"left": x, "right": y, "reason": "similar_title_requires_review"}
             for x in only_a for y in only_b if a[x].get("title") and b[y].get("title")
             and SequenceMatcher(None, str(a[x]["title"]).casefold(),
                                 str(b[y]["title"]).casefold()).ratio() >= .9]
    return {"shared": sorted(a.keys() & b.keys()), "left_only": only_a, "right_only": only_b,
            "similarity_hints": hints,
            "unresolved_left": [r for r in left if not resolve_identity(r)["identity"]],
            "unresolved_right": [r for r in right if not resolve_identity(r)["identity"]]}


def metadata_snapshots(records: Sequence[dict], *, coordinator: DiscoveryCoordinator,
                       request: DiscoveryRequest) -> dict:
    candidates = tuple(candidate_record(record) for record in records)
    batch = DiscoveryCoordinator((), enrichers=coordinator.enrichers).discover(
        request.with_seed_candidates(candidates))
    merged = sanitize_artifact_value(merge_collection(
        [*records, *(item.to_dict() for item in batch.candidates)]))
    snapshots = [{"schema_version": 1, "fields": record,
                  "field_sources": record.get("field_provenance", {}),
                  "conflicts": [c for c in merged["conflicts"]
                                if c["identity"] == resolve_identity(record)["identity"]],
                  "content_sha256": content_hash(record)} for record in merged["records"]]
    for snapshot in snapshots:
        validate_contract(snapshot, "metadata-snapshot.schema.json")
    return {**merged, "snapshots": snapshots,
            "diagnostics": [asdict(item) for item in batch.diagnostics]}


def candidate_record(record: Mapping) -> CandidateMetadata:
    """Default only bookkeeping fields; leave missing bibliographic facts empty."""
    identity = resolve_identity(record)
    defaults = {"key": identity["identity"] or "unresolved", "title": "", "year": 0,
                "venue": "", "relevance_score": 0, "hard_gates_passed": False,
                "evidence_fields": [k for k in ("title", "abstract", "doi", "official_url")
                                    if record.get(k)]}
    return CandidateMetadata.from_dict({**defaults, **record})


def verify_local_pair(pdf: Path, bibtex: Path, expected: Mapping) -> dict:
    metadata = PaperMetadata(title=expected["title"], authors=tuple(expected.get("authors", [])),
        year=int(expected["year"]), venue=expected.get("venue", ""), doi=expected.get("doi"),
        publisher=expected.get("publisher") or "user-supplied",
        landing_url=expected.get("official_url") or expected.get("landing_url") or "https://local.invalid/",
        authors_complete=expected.get("authors_complete", True))
    document = SourceDocument(metadata=metadata, pdf_url="", bibtex_url="", allowed_hosts=frozenset())
    validate_manual_pair(document, pdf, bibtex)
    return {**OperationResult(completed=1).to_dict(), "source_trust": "user-supplied",
            "official_acquisition_complete": False,
            "artifacts": [artifact_reference(pdf), artifact_reference(bibtex)]}


def validate_reviews(records: Sequence[dict], decisions: Sequence[dict], *, policy: str) -> list[dict]:
    from acquire_research_papers.review_contracts import review_metadata
    if policy not in {"identity", "relevance"}:
        raise ValueError("use evidence validation with exact full-text artifacts for fulltext policy")
    indexed = {}
    for record in records:
        identity = resolve_identity(record)["identity"]
        if not identity:
            continue
        if identity in indexed and indexed[identity] != record:
            raise ValueError("conflicting duplicate identity; merge and review the resulting record explicitly")
        indexed[identity] = record
    seen, validated = set(), []
    for decision in decisions:
        validate_contract(decision, "capability-review.schema.json")
        review_metadata(decision)
        key = decision.get("identity")
        if key in seen or key not in indexed:
            raise ValueError("review references a duplicate or unknown exact identity")
        seen.add(key)
        record = indexed[key]
        if decision.get("input_sha256") != content_hash(record):
            raise ValueError("review input hash mismatch")
        if decision.get("policy") != policy or not str(decision.get("policy_version", "")).strip():
            raise ValueError("review policy and version are required")
        if decision.get("decision") not in {"accept", "reject", "pending"} or not str(
                decision.get("reason", "")).strip():
            raise ValueError("review decision and reason are required")
        evidence = decision.get("evidence", [])
        if not isinstance(evidence, list) or not evidence or not all(
                isinstance(field, str) and record.get(field) for field in evidence):
            raise ValueError("review evidence must reference present fields")
        if decision["decision"] == "accept" and policy == "relevance":
            if not {"title", "abstract"}.issubset(evidence) or not record.get("hard_gates_passed"):
                raise ValueError("relevance acceptance requires title, abstract and hard gates")
        if decision["decision"] == "accept" and policy == "identity":
            if not {"doi", "official_url"}.intersection(evidence):
                raise ValueError("identity acceptance requires exact identity evidence")
        validated.append(dict(decision))
    return validated


def freeze_selection(records: Sequence[dict], decisions: Sequence[dict], root: Path,
                     *, policy: str = "relevance", maximum: int | None = None) -> dict:
    reviews = validate_reviews(records, decisions, policy=policy)
    accepted = {d["identity"] for d in reviews if d["decision"] == "accept"}
    if maximum is not None and maximum < 0:
        raise ValueError("maximum must be nonnegative")
    selected = [r for r in merge_collection(records)["records"]
                if resolve_identity(r)["identity"] in accepted]
    if maximum is not None:
        selected = selected[:maximum]
    if any(not str(r.get("title", "")).strip() or not isinstance(r.get("year"), int)
           or not 1000 <= r["year"] <= 9999 for r in selected):
        raise ValueError("accepted selection records require a title and four-digit publication year")
    selection = build_selection_records((candidate_record(sanitize_artifact_value(r)) for r in selected),
                                        venues=(), delivery={})
    spec = {"capability": "selection", "policy": policy, "maximum": maximum,
            "records_sha256": content_hash(records), "reviews_sha256": content_hash(reviews)}
    manifest = root / "selection-manifest.json"
    if manifest.exists():
        store = SelectionStore.load(manifest)
        if store.manifest["spec"] != spec:
            raise ValueError("selection is frozen; use a new run for changed inputs")
    else:
        store = SelectionStore.write(root, spec, selection)
    return {**OperationResult(completed=len(store.records), outputs=(str(store.manifest_path),
                    str(store.selected_path))).to_dict(), "selection": str(store.manifest_path)}
