import json
from pathlib import Path

from acquire_research_papers.schema_resources import resolve_schema_root, schema


def test_schema_root_prefers_repository_during_source_execution(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    package = repository / "src" / "acquire_research_papers"
    repository_schemas = repository / "schemas"
    bundled_schemas = package / "_schemas"
    repository_schemas.mkdir(parents=True)
    bundled_schemas.mkdir(parents=True)

    assert resolve_schema_root(package, repository) == repository_schemas


def test_schema_root_falls_back_to_wheel_bundle(tmp_path: Path) -> None:
    package = tmp_path / "site-packages" / "acquire_research_papers"
    bundled_schemas = package / "_schemas"
    bundled_schemas.mkdir(parents=True)

    assert resolve_schema_root(package, tmp_path / "missing-repository") == bundled_schemas


def test_schema_loader_rejects_paths_outside_schema_root(tmp_path: Path) -> None:
    root = tmp_path / "schemas"
    root.mkdir()
    (root / "valid.json").write_text(json.dumps({"type": "object"}), encoding="utf-8")

    assert schema("valid.json", root=root) == {"type": "object"}
    try:
        schema("../outside.json", root=root)
    except ValueError as exc:
        assert "schema name" in str(exc)
    else:
        raise AssertionError("schema loader accepted a path traversal")
