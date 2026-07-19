from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


class EvidenceValidationError(ValueError):
    """An evidence claim overstates what was actually read."""


_RELATIONS = {
    "direct-support",
    "indirect-support",
    "qualifies",
    "contradicts",
    "background",
}
_READ_SCOPES = {"metadata-only", "abstract-only", "full-text"}


@dataclass(frozen=True)
class EvidenceRecord:
    claim_id: str
    paper_id: str
    relation: str
    read_scope: str
    section: str | None
    page: int | None
    excerpt: str
    explanation: str
    strength: str = "moderate"
    uncertainty: str = ""

    def validate(self) -> EvidenceRecord:
        if not self.claim_id.strip() or not self.paper_id.strip():
            raise EvidenceValidationError("claim_id and paper_id are required")
        if self.relation not in _RELATIONS:
            raise EvidenceValidationError(f"unsupported evidence relation: {self.relation}")
        if self.read_scope not in _READ_SCOPES:
            raise EvidenceValidationError(f"unsupported read scope: {self.read_scope}")
        if not self.explanation.strip():
            raise EvidenceValidationError("evidence explanation is required")
        if len(self.excerpt) > 500:
            raise EvidenceValidationError("evidence excerpt must remain a short excerpt")
        if self.page is not None and self.page < 1:
            raise EvidenceValidationError("evidence page must be positive")
        if self.relation in {"direct-support", "contradicts"}:
            if self.read_scope != "full-text":
                raise EvidenceValidationError(
                    f"{self.relation} requires a full text read, not {self.read_scope}"
                )
            if not (self.section and self.section.strip()) and self.page is None:
                raise EvidenceValidationError("direct evidence requires a section or page location")
            if not self.excerpt.strip():
                raise EvidenceValidationError("direct evidence requires a short exact excerpt")
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
