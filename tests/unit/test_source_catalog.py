from acquire_research_papers.source_catalog import describe_sources


def request(venues):
    return {"name": "test", "target": {"minimum": 1, "maximum": 5},
            "scope": {"years": {"include": [2024, 2025]}, "venues": venues}}


def test_catalog_distinguishes_official_indexes_metadata_and_artifacts():
    result = describe_sources(request([
        {"name": "ACL", "kind": "conference", "years": [2025]},
        {"name": "IJCAI", "kind": "conference"},
        {"name": "IEEE Transactions on Tests", "publisher": "IEEE", "issn": ["1234-5678"]},
        {"name": "ACM Test", "publisher": "ACM", "kind": "conference"},
        {"name": "Unknown", "publisher": "Unknown", "kind": "conference", "collection_doi": ["10.1234/test"]},
    ]))
    slices = result["requested_slices"]
    assert len(slices) == 9
    acl = next(s for s in slices if s["venue"] == "ACL")
    assert acl["year"] == 2025
    assert acl["official_indexes"] == ["acl-anthology"]
    assert next(s for s in slices if s["venue"] == "IJCAI")["official_indexes"] == ["ijcai-proceedings"]
    ieee = next(s for s in slices if s["publisher"] == "IEEE")
    assert ieee["crossref"]["identifier"] == "issn"
    assert ieee["official_indexes"] == []
    acm = next(s for s in slices if s["publisher"] == "ACM")
    assert acm["crossref"]["available"] is False
    unknown = next(s for s in slices if s["publisher"] == "Unknown")
    assert unknown["crossref"]["available"] is True
    assert unknown["acquisition"] == "unknown"
    assert all(s["observed_coverage"] is None for s in slices)
    assert result["universal_completeness"] is False


def test_source_cli_does_not_construct_application(monkeypatch, capsys):
    import json
    from acquire_research_papers.cli import Application, run_cli
    monkeypatch.setattr(Application, "default", lambda **_: (_ for _ in ()).throw(AssertionError("network services")))
    assert run_cli(["sources"]) == 0
    assert json.loads(capsys.readouterr().out)["sources"]


def test_source_cli_validates_spec_without_services(monkeypatch, capsys, tmp_path):
    import json
    from pathlib import Path
    from acquire_research_papers.cli import Application, run_cli
    monkeypatch.setattr(Application, "default", lambda **_: (_ for _ in ()).throw(AssertionError("network services")))
    template = Path(__file__).resolve().parents[2] / "skills/acquire-research-papers/examples/inputs/corpus.yaml"
    spec = tmp_path / "corpus.yaml"
    spec.write_text(template.read_text(encoding="utf-8").replace("venues: []", "venues: [{name: ACL}]"), encoding="utf-8")
    assert run_cli(["sources", "--spec", str(spec)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["requested_slices"]
    assert all(row["observed_coverage"] is None for row in result["requested_slices"])
    assert run_cli(["sources", "--spec", "missing.yaml"]) == 64
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_official_index_respects_live_publication_type_gate():
    spec = request([{"name": "ACL"}, {"name": "IJCAI"}])
    spec["scope"]["publication_types"] = {"include": ["short"]}
    assert all(not row["official_indexes"] for row in describe_sources(spec)["requested_slices"])
