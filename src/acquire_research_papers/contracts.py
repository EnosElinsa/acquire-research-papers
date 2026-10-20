"""Public contract validation with diagnostics that never echo field values."""
from __future__ import annotations

import json
from jsonschema import Draft202012Validator

from acquire_research_papers.schema_resources import schema


def validate_contract(value, name: str) -> None:
    errors = list(Draft202012Validator(schema(name)).iter_errors(
        json.loads(json.dumps(value, ensure_ascii=False))))
    if errors:
        error = min(errors, key=lambda item: tuple(str(p) for p in item.absolute_path))
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise ValueError(f"{name}: invalid {location} ({error.validator})")
