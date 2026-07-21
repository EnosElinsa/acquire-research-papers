from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"


class SpecValidationError(ValueError):
    """A structured task file does not satisfy its public contract."""


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SpecValidationError(f"unable to read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise SpecValidationError("$: expected an object")
    return value


def _validate(value: dict[str, Any], schema_name: str) -> dict[str, Any]:
    schema = json.loads((SCHEMA_ROOT / schema_name).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda item: list(item.path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path)
        raise SpecValidationError(f"{location or '$'}: {error.message}")
    return copy.deepcopy(value)


def load_corpus_spec(path: Path) -> dict[str, Any]:
    spec = _validate(_read_mapping(path), "corpus-spec.schema.json")
    target = spec["target"]
    minimum = target["minimum"]
    maximum = target["maximum"]
    if maximum < minimum:
        raise SpecValidationError("target.maximum: must be greater than or equal to target.minimum")
    target.setdefault("preferred", (minimum + maximum) // 2)
    if not minimum <= target["preferred"] <= maximum:
        raise SpecValidationError("target.preferred: must be between target.minimum and target.maximum")
    spec.setdefault("scope", {})
    spec.setdefault("quotas", {})
    spec.setdefault(
        "delivery",
        {
            "require_pdf": True,
            "require_official_bibtex": True,
            "export_markdown": False,
            "profile": "generic",
        },
    )
    for index, group in enumerate(spec["quotas"].get("groups", [])):
        group_maximum = group.get("maximum")
        if group_maximum is not None and group_maximum < group["minimum"]:
            raise SpecValidationError(
                f"quotas.groups.{index}.maximum: must be greater than or equal to minimum"
            )
    delivery = spec["delivery"]
    template = str(delivery.get("naming_template", ""))
    if delivery.get("profile") == "numbered" and not {
        "{number}",
        "{ext}",
    }.issubset(template):
        raise SpecValidationError(
            "delivery.naming_template: numbered profile requires {number} and {ext}"
        )
    return spec


def load_research_brief(path: Path) -> dict[str, Any]:
    brief = _validate(_read_mapping(path), "research-brief.schema.json")
    brief.setdefault("work_under_review", {})
    brief.setdefault("claims", [])
    brief.setdefault("seed_papers", [])
    brief.setdefault("scope", {})
    brief.setdefault("delivery", {"write_narrative": False, "export_markdown": False})
    return brief
