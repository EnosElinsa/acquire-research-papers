from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from acquire_research_papers.acquisition.base import AcquiredPair
from acquire_research_papers.artifacts import (
    atomic_write_bytes,
    sha256_bytes,
    sha256_file,
    validate_pdf,
)
from acquire_research_papers.bibliography import parse_bibtex, verify_bibliography


@dataclass(frozen=True)
class DeliveryResult:
    pdf: Path
    bibtex: Path
    provenance: Path
    status: str = "delivered"


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    slug = re.sub(r"[^\w.-]+", "_", normalized, flags=re.UNICODE).strip("._")
    return (slug or "paper")[:80]


class GenericDelivery:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _paths(self, pair: AcquiredPair, paper_id: str) -> DeliveryResult:
        bundle = self.root / f"{_slug(pair.document.metadata.title)}--{paper_id[:12]}"
        return DeliveryResult(
            pdf=bundle / "paper.pdf",
            bibtex=bundle / "citation.bib",
            provenance=bundle / "provenance.json",
        )

    def _existing_is_valid(
        self,
        result: DeliveryResult,
        pair: AcquiredPair,
        paper_id: str,
    ) -> bool:
        if not all(path.is_file() for path in (result.pdf, result.bibtex, result.provenance)):
            return False
        try:
            payload = json.loads(result.provenance.read_text(encoding="utf-8"))
            validate_pdf(result.pdf)
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        return (
            payload.get("paper_id") == paper_id
            and payload.get("pdf_sha256") == sha256_file(result.pdf) == sha256_bytes(pair.pdf_bytes)
            and payload.get("bibtex_sha256") == sha256_bytes(pair.bibtex_text.encode("utf-8"))
            and result.bibtex.read_text(encoding="utf-8") == pair.bibtex_text
        )

    def deliver(self, *, pair: AcquiredPair, paper_id: str) -> DeliveryResult:
        parsed = parse_bibtex(pair.bibtex_text)
        verify_bibliography(pair.document.metadata, parsed)
        result = self._paths(pair, paper_id)
        if self._existing_is_valid(result, pair, paper_id):
            return result

        atomic_write_bytes(result.pdf, pair.pdf_bytes, validator=validate_pdf)
        atomic_write_bytes(result.bibtex, pair.bibtex_text.encode("utf-8"))
        provenance = {
            "paper_id": paper_id,
            "metadata": asdict(pair.document.metadata),
            "official_landing_url": pair.document.metadata.landing_url,
            "official_pdf_url": pair.document.pdf_url,
            "official_bibtex_url": pair.document.bibtex_url,
            "pdf_sha256": sha256_bytes(pair.pdf_bytes),
            "bibtex_sha256": sha256_bytes(pair.bibtex_text.encode("utf-8")),
            "delivered_at": datetime.now(UTC).isoformat(),
        }
        atomic_write_bytes(
            result.provenance,
            (json.dumps(provenance, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        return result
