from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def resolve_schema_root(package_root: Path, repository_root: Path) -> Path:
    repository_schemas = repository_root.resolve() / "schemas"
    if repository_schemas.is_dir():
        return repository_schemas
    bundled_schemas = package_root.resolve() / "_schemas"
    if bundled_schemas.is_dir():
        return bundled_schemas
    raise RuntimeError("public JSON schemas are not installed")


SCHEMA_ROOT = resolve_schema_root(
    Path(__file__).resolve().parent,
    Path(__file__).resolve().parents[2],
)


def schema(name: str, *, root: Path = SCHEMA_ROOT) -> dict[str, Any]:
    if not name or Path(name).name != name or Path(name).suffix.casefold() != ".json":
        raise ValueError("schema name must be one JSON filename")
    try:
        value = json.loads((root.resolve() / name).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"schema could not be loaded: {name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"schema must contain an object: {name}")
    return value
