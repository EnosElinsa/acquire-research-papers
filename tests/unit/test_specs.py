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


def test_corpus_spec_accepts_generic_layout_metadata(tmp_path: Path) -> None:
    path = tmp_path / "layout.yaml"
    path.write_text(
        "mode: corpus\nname: layout\ntarget:\n  minimum: 1\n  maximum: 2\n"
        "scope:\n  venues:\n    - name: Invented Proceedings\n"
        "      short_name: IP\n      publisher: Invented Society\n",
        encoding="utf-8",
    )

    spec = load_corpus_spec(path)

    assert spec["scope"]["venues"][0]["short_name"] == "IP"


def test_corpus_spec_rejects_group_maximum_below_minimum(tmp_path: Path) -> None:
    path = tmp_path / "bad-group.yaml"
    path.write_text(
        "mode: corpus\nname: bad-group\ntarget:\n  minimum: 1\n  maximum: 2\n"
        "quotas:\n  groups:\n    - name: journals\n      minimum: 2\n      maximum: 1\n",
        encoding="utf-8",
    )

    with pytest.raises(SpecValidationError, match="quotas.groups.0.maximum"):
        load_corpus_spec(path)


def test_numbered_delivery_requires_number_and_extension_tokens(tmp_path: Path) -> None:
    path = tmp_path / "bad-layout.yaml"
    path.write_text(
        "mode: corpus\nname: bad-layout\ntarget:\n  minimum: 1\n  maximum: 2\n"
        "delivery:\n  profile: numbered\n  naming_template: papers/fixed.pdf\n",
        encoding="utf-8",
    )

    with pytest.raises(SpecValidationError, match="delivery.naming_template"):
        load_corpus_spec(path)


def test_numbered_delivery_accepts_number_and_extension_tokens(tmp_path: Path) -> None:
    path = tmp_path / "numbered-layout.yaml"
    path.write_text(
        "mode: corpus\nname: numbered-layout\ntarget:\n  minimum: 1\n  maximum: 2\n"
        "delivery:\n  profile: numbered\n"
        "  naming_template: '2026.7.18 {publisher}/{number}.{ext}'\n",
        encoding="utf-8",
    )

    spec = load_corpus_spec(path)

    assert spec["delivery"]["profile"] == "numbered"


def test_corpus_spec_accepts_optional_venue_specific_years(tmp_path: Path) -> None:
    path = tmp_path / "venue-years.yaml"
    path.write_text(
        "mode: corpus\nname: editions\ntarget:\n  minimum: 1\n  maximum: 2\n"
        "scope:\n  venues:\n    - name: Conference 2025\n      years: [2025]\n"
        "  years:\n    include: [2025, 2024]\n",
        encoding="utf-8",
    )

    spec = load_corpus_spec(path)

    assert spec["scope"]["venues"][0]["years"] == [2025]


def test_corpus_spec_accepts_crossref_collection_dois(tmp_path: Path) -> None:
    path = tmp_path / "collection.yaml"
    path.write_text(
        "mode: corpus\nname: collection\ntarget:\n  minimum: 1\n  maximum: 2\n"
        "scope:\n  venues:\n    - name: Proceedings Collection\n"
        "      collection_doi: [10.1145/123, 10.1145/456]\n",
        encoding="utf-8",
    )

    spec = load_corpus_spec(path)

    assert spec["scope"]["venues"][0]["collection_doi"] == [
        "10.1145/123",
        "10.1145/456",
    ]
