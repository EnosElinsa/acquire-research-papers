from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from string import Formatter
from typing import Any

from acquire_research_papers.artifacts import atomic_write_bytes, sha256_bytes
from acquire_research_papers.discovery.contracts import CandidateMetadata, VenueScope
from acquire_research_papers.models import normalize_doi


_WINDOWS_RESERVED = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)
_TEMPLATE_FIELDS = frozenset(
    {"publisher", "venue", "venue_short", "year", "number", "ext"}
)
_TUPLE_FIELDS = frozenset({"authors", "keywords", "evidence_fields"})


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold()))


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    slug = re.sub(r"[^\w.-]+", "_", normalized, flags=re.UNICODE).strip("._")
    return (slug or "paper")[:80]


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.name:
        raise ValueError("unsafe relative delivery path")
    for part in path.parts:
        reserved_base = part.rstrip(" .").split(".", 1)[0].casefold()
        if (
            not part
            or part != part.rstrip(" .")
            or re.search(r'[<>:"|?*]', part)
            or reserved_base in _WINDOWS_RESERVED
        ):
            raise ValueError("unsafe relative delivery path")
    return path.as_posix()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _selection_identity(candidate: CandidateMetadata) -> str:
    doi = normalize_doi(candidate.doi)
    if doi:
        return f"doi:{doi}"
    if candidate.official_url:
        return f"url:{candidate.official_url.rstrip('/').casefold()}"
    return "meta:" + "|".join(
        (_normalized(candidate.title), str(candidate.year), _normalized(candidate.venue))
    )


def _selection_id(candidate: CandidateMetadata) -> str:
    return sha256_bytes(_selection_identity(candidate).encode("utf-8"))[:24]


def _venue_scope(candidate: CandidateMetadata, venues: tuple[VenueScope, ...]) -> VenueScope:
    candidate_venue = _normalized(candidate.venue)
    for venue in venues:
        if candidate_venue in {_normalized(value) for value in venue.all_names}:
            return venue
    return VenueScope(name=candidate.venue)


@dataclass(frozen=True)
class SelectionRecord:
    selection_id: str
    ordinal: int
    key: str
    title: str
    authors: tuple[str, ...]
    doi: str | None
    official_url: str | None
    venue: str
    venue_short: str
    publisher: str
    year: int
    publication_date: str | None
    publication_type: str | None
    track: str | None
    abstract: str
    keywords: tuple[str, ...]
    evidence_fields: tuple[str, ...]
    relative_pdf: str
    relative_bibtex: str
    relative_provenance: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SelectionRecord:
        payload = dict(value)
        for field in _TUPLE_FIELDS:
            payload[field] = tuple(str(item) for item in payload.get(field, ()))
        try:
            return cls(**payload)
        except TypeError as exc:
            raise ValueError("selection record does not match schema version 1") from exc


def _record(
    candidate: CandidateMetadata,
    *,
    venue: VenueScope,
    ordinal: int,
    pdf: str,
    bibtex: str,
    provenance: str,
) -> SelectionRecord:
    return SelectionRecord(
        selection_id=_selection_id(candidate),
        ordinal=ordinal,
        key=candidate.key,
        title=candidate.title,
        authors=candidate.authors,
        doi=normalize_doi(candidate.doi),
        official_url=candidate.official_url,
        venue=candidate.venue,
        venue_short=venue.short_name or candidate.venue,
        publisher=venue.publisher,
        year=candidate.year,
        publication_date=candidate.publication_date,
        publication_type=candidate.publication_type,
        track=candidate.track,
        abstract=candidate.abstract,
        keywords=candidate.keywords,
        evidence_fields=candidate.evidence_fields,
        relative_pdf=pdf,
        relative_bibtex=bibtex,
        relative_provenance=provenance,
    )


def _template_fields(template: str) -> frozenset[str]:
    fields = frozenset(
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name is not None
    )
    unknown = fields - _TEMPLATE_FIELDS
    if unknown:
        raise ValueError(f"unknown delivery template fields: {sorted(unknown)}")
    return fields


def build_selection_records(
    candidates: Iterable[CandidateMetadata],
    *,
    venues: tuple[VenueScope, ...],
    delivery: Mapping[str, Any],
) -> tuple[SelectionRecord, ...]:
    profile = str(delivery.get("profile", "generic"))
    template = str(delivery.get("naming_template", ""))
    fields = _template_fields(template) if profile == "numbered" else frozenset()
    if profile == "numbered":
        if not {"number", "ext"}.issubset(fields):
            raise ValueError("numbered delivery template requires {number} and {ext}")
        filename_fields = _template_fields(PurePosixPath(template).name)
        if not {"number", "ext"}.issubset(filename_fields):
            raise ValueError("{number} and {ext} must appear in the delivery filename")

    records: list[SelectionRecord] = []
    folder_counts: dict[str, int] = {}
    selection_ids: set[str] = set()
    used_paths: set[str] = set()
    for global_ordinal, candidate in enumerate(candidates, start=1):
        venue = _venue_scope(candidate, venues)
        selection_id = _selection_id(candidate)
        if selection_id in selection_ids:
            raise ValueError(f"duplicate selected paper identity: {selection_id}")
        selection_ids.add(selection_id)

        if profile == "numbered":
            metadata: dict[str, Any] = {
                "publisher": venue.publisher,
                "venue": venue.name,
                "venue_short": venue.short_name,
                "year": candidate.year,
                "number": 1,
                "ext": "pdf",
            }
            for field in fields - {"number", "ext"}:
                if not str(metadata[field]).strip():
                    raise ValueError(f"delivery template field {field} is empty")
            first_pdf = _safe_relative(template.format_map(metadata))
            parent = PurePosixPath(first_pdf).parent.as_posix()
            ordinal = folder_counts.get(parent, 0) + 1
            folder_counts[parent] = ordinal
            metadata["number"] = ordinal
            metadata["ext"] = "pdf"
            pdf = _safe_relative(template.format_map(metadata))
            metadata["ext"] = "bib"
            bibtex = _safe_relative(template.format_map(metadata))
            if PurePosixPath(pdf).parent != PurePosixPath(bibtex).parent:
                raise ValueError("PDF and BibTeX templates must render to the same folder")
            provenance = _safe_relative(
                str(PurePosixPath(pdf).parent / f"{ordinal}.provenance.json")
            )
        else:
            ordinal = global_ordinal
            bundle = _safe_relative(f"{_slug(candidate.title)}--{selection_id[:12]}")
            pdf = _safe_relative(f"{bundle}/paper.pdf")
            bibtex = _safe_relative(f"{bundle}/citation.bib")
            provenance = _safe_relative(f"{bundle}/provenance.json")

        candidate_paths = {pdf.casefold(), bibtex.casefold(), provenance.casefold()}
        if len(candidate_paths) != 3 or candidate_paths & used_paths:
            raise ValueError("delivery layout contains a path collision")
        used_paths.update(candidate_paths)
        records.append(
            _record(
                candidate,
                venue=venue,
                ordinal=ordinal,
                pdf=pdf,
                bibtex=bibtex,
                provenance=provenance,
            )
        )
    return tuple(records)


def _jsonl(records: tuple[SelectionRecord, ...]) -> bytes:
    return "".join(
        json.dumps(
            asdict(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for record in records
    ).encode("utf-8")


@dataclass(frozen=True)
class SelectionStore:
    manifest_path: Path
    selected_path: Path
    records: tuple[SelectionRecord, ...]
    manifest: dict[str, Any]

    @classmethod
    def write(
        cls,
        root: Path,
        spec: Mapping[str, Any],
        records: Iterable[SelectionRecord],
        *,
        discovery_summary: Mapping[str, Any] | None = None,
    ) -> SelectionStore:
        destination = root.resolve()
        selected_path = destination / "selected-papers.jsonl"
        manifest_path = destination / "selection-manifest.json"
        selected_records = tuple(records)
        selected_bytes = _jsonl(selected_records)
        spec_payload = dict(spec)
        summary = dict(discovery_summary or {})
        reserved = {
            "schema_version",
            "spec",
            "spec_sha256",
            "selected_file",
            "selected_sha256",
            "selected_count",
        }
        collisions = reserved & summary.keys()
        if collisions:
            raise ValueError(f"discovery summary replaces reserved fields: {sorted(collisions)}")
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "spec": spec_payload,
            "spec_sha256": sha256_bytes(_canonical_json(spec_payload)),
            "selected_file": selected_path.name,
            "selected_sha256": sha256_bytes(selected_bytes),
            "selected_count": len(selected_records),
            **summary,
        }
        atomic_write_bytes(selected_path, selected_bytes)
        atomic_write_bytes(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            + b"\n",
        )
        return cls(manifest_path, selected_path, selected_records, manifest)

    @classmethod
    def load(cls, manifest_path: Path) -> SelectionStore:
        resolved_manifest = manifest_path.resolve()
        try:
            manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("selection manifest could not be read") from exc
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise ValueError("unsupported selection manifest schema")
        selected_name = _safe_relative(str(manifest.get("selected_file", "")))
        selected_path = (resolved_manifest.parent / Path(selected_name)).resolve()
        if (
            selected_path == resolved_manifest.parent
            or resolved_manifest.parent not in selected_path.parents
        ):
            raise ValueError("selection path escapes manifest directory")
        try:
            selected_bytes = selected_path.read_bytes()
        except OSError as exc:
            raise ValueError("selected paper list could not be read") from exc
        if sha256_bytes(selected_bytes) != manifest.get("selected_sha256"):
            raise ValueError("selection SHA-256 mismatch")
        records: list[SelectionRecord] = []
        try:
            for line in selected_bytes.decode("utf-8").splitlines():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("selection record must be an object")
                records.append(SelectionRecord.from_dict(value))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("selected paper list is invalid") from exc
        if len(records) != manifest.get("selected_count"):
            raise ValueError("selection record count mismatch")
        return cls(resolved_manifest, selected_path, tuple(records), manifest)

