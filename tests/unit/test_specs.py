from pathlib import Path

import pytest

from acquire_research_papers.specs import SpecValidationError, load_corpus_spec, load_research_brief


def test_corpus_spec_defaults_preferred_to_range_midpoint(tmp_path: Path) -> None:
    path = tmp_path / "job.yaml"
    path.write_text(
        "mode: corpus\nname: test\ntarget:\n  minimum: 60\n  maximum: 100\n",
        encoding="utf-8",
    )
    spec = load_corpus_spec(path)
    assert spec["target"]["preferred"] == 80


def test_corpus_spec_rejects_maximum_below_minimum(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        "mode: corpus\nname: bad\ntarget:\n  minimum: 100\n  maximum: 60\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecValidationError, match="target.maximum"):
        load_corpus_spec(path)


def test_research_brief_defaults_delivery_flags(tmp_path: Path) -> None:
    path = tmp_path / "research.json"
    path.write_text(
        '{"schema_version": 1, "mode": "research", "question_type": "gap-analysis", '
        '"research_question": "What is the gap?"}',
        encoding="utf-8",
    )
    brief = load_research_brief(path)
    assert brief["delivery"] == {"write_narrative": False, "export_markdown": False}


def test_unknown_spec_fields_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "unknown.yaml"
    path.write_text(
        "mode: corpus\nname: test\ntarget:\n  minimum: 1\n  maximum: 2\nsecret: nope\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecValidationError, match="secret"):
        load_corpus_spec(path)
