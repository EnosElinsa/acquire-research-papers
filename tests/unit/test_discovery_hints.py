from __future__ import annotations

from types import SimpleNamespace

import pytest

from acquire_research_papers import host_support
from acquire_research_papers.cli import _corpus_discovery_next_actions
from acquire_research_papers.discovery.contracts import DiscoveryDiagnostic


def result(*, pending: int = 0, warnings: tuple = ()) -> SimpleNamespace:
    return SimpleNamespace(pending_metadata=pending, coverage_warnings=warnings)


def test_missing_abstracts_without_keys_name_the_config_command_for_each_missing_key():
    actions = _corpus_discovery_next_actions(result(pending=3), ("semantic_scholar", "openalex"))

    assert [(item["action"], item.get("command")) for item in actions] == [
        ("config setup", "arp config setup semantic_scholar"),
        ("config setup", "arp config setup openalex"),
        ("rerun", None),
    ]
    assert "3 candidates still lack an abstract" in actions[-1]["reason"]
    assert "rerun the same command with the same output" in actions[-1]["reason"]
    (*_, single) = _corpus_discovery_next_actions(result(pending=1), ("openalex",))
    assert single["reason"].startswith("1 candidate still lacks an abstract;")


def test_no_hint_when_nothing_is_pending_or_every_key_is_configured():
    assert _corpus_discovery_next_actions(result(pending=0), ("openalex",)) == []
    assert _corpus_discovery_next_actions(result(pending=5), ()) == []


def test_a_coverage_warning_becomes_a_check_coverage_action():
    lag = DiscoveryDiagnostic("openalex-venue", "venue-enumeration", "possible_upstream_lag",
                              "OpenAlex lists 25 works for INFOCOM 2025 against 262 for 2024",
                              venue="INFOCOM", year=2025)

    (action,) = _corpus_discovery_next_actions(result(warnings=(lag,)), ())

    assert (action["action"], action["venue"], action["year"], action["reason"]) == (
        "check_coverage", "INFOCOM", 2025, "possible_upstream_lag")
    assert action["message"].startswith("OpenAlex lists 25 works for INFOCOM 2025")
    assert "same output later reads this slice again" in action["message"]


def test_doctor_notes_missing_discovery_keys_only_from_a_checked_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.setenv("OPENALEX_API_KEY", "from-environment")
    checked = {"status": "checked", "api_keys": {"semantic_scholar": False, "openalex": False,
                                                 "elsevier": False}}

    assert host_support._missing_discovery_keys(checked) == ["semantic_scholar"]
    assert "arp config setup semantic_scholar" in host_support.DISCOVERY_KEY_NOTES["semantic_scholar"]
    assert host_support._missing_discovery_keys(
        {"status": "legacy_unchecked", "api_keys": {"semantic_scholar": None}}) == []
