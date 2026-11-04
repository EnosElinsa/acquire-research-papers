from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("release_smoke", ROOT / "scripts" / "release_smoke.py")
release_smoke = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = release_smoke
spec.loader.exec_module(release_smoke)


def fake_cli(workspace: Path, *, fetch_outcomes: dict[str, str] | None = None):
    outcomes = {reference: expected[0] for _, reference, expected in release_smoke.FETCHES}
    outcomes.update(fetch_outcomes or {})
    calls = []

    def invoke(*arguments: str, raw: bool = False):
        calls.append(arguments)
        command = arguments[0]
        if command == "--version":
            return 0, {"version": "9.9.9"}, ""
        if command == "doctor":
            return 0, {"skill": {"runtime_matches_pin": True}}, ""
        if command == "manual-fetch":
            return 0, {}, "usage: ... --open-all ..."
        if command == "sources":
            return 0, {"venue_presets": [{}] * 3, "requested_slices": [
                {"venue": "INFOCOM", "preset": "ieee-infocom", "crossref": {"available": False},
                 "openalex_venue": {"sources": ["S7407087743"]}},
                {"venue": "IEEE TMC", "preset": "ieee-tmc", "crossref": {"available": True},
                 "openalex_venue": {"sources": []}}]}, ""
        if command == "fetch":
            outcome = outcomes[arguments[2]]
            if outcome == "delivered":
                return 0, {"status": "delivered"}, ""
            return 69, {"status": "error", "error_code": outcome}, ""
        if command == "discover":
            output = Path(arguments[arguments.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "coverage.jsonl").write_text(json.dumps(
                {"provider_id": "pmlr", "state": "complete",
                 "records_recognized": release_smoke.ICML_2023_PAPERS}) + "\n", encoding="utf-8")
            (output / "candidates.jsonl").write_text("".join(
                json.dumps({"abstract": "a", "official_url": "u"}) + "\n"
                for _ in range(release_smoke.ICML_2023_PAPERS)), encoding="utf-8")
            return 0, {"status": "review_required"}, ""
        if command == "--background":
            return 0, {"status": "started"}, ""
        if command == "job":
            return 0, {"status": "finished", "exit_code": 0, "result": {"status": "delivered"}}, ""
        raise AssertionError(arguments)

    return invoke, calls


def run(tmp_path: Path, **outcomes):
    invoke, calls = fake_cli(tmp_path, **outcomes)
    lines: list[str] = []
    checks = release_smoke.Smoke(invoke, tmp_path, version="9.9.9", presets=3,
                                 progress=lines.append).run()
    return checks, calls, lines


def test_every_check_passes_when_the_cli_answers_as_expected(tmp_path):
    checks, calls, lines = run(tmp_path)

    assert all(item["passed"] for item in checks), [i for i in checks if not i["passed"]]
    assert len(checks) == 17 and len(lines) == 17
    assert sum(call[0] == "discover" for call in calls) == 2
    springer = next(item for item in checks if item["check"] == "fetch Springer URL")
    assert springer["expected"] == ["delivered", "access_required"]


def test_an_unexpected_outcome_fails_only_its_check(tmp_path):
    elsevier = next(ref for label, ref, _ in release_smoke.FETCHES if label == "Elsevier DOI")
    springer = next(ref for label, ref, _ in release_smoke.FETCHES if label == "Springer URL")

    checks, _, lines = run(tmp_path, fetch_outcomes={elsevier: "delivered",
                                                     springer: "access_required"})

    failed = [item["check"] for item in checks if not item["passed"]]
    assert failed == ["fetch Elsevier DOI"]
    assert any(line.startswith("FAIL fetch Elsevier DOI") for line in lines)
