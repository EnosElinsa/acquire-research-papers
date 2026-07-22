from __future__ import annotations

import json
from pathlib import Path

from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.discovery.contracts import CandidateMetadata, DiscoveryBatch
from acquire_research_papers.discovery.corpus import CorpusDiscoveryWorkflow


def test_review_corpus_cli_imports_decisions_and_reports_frozen_selection(
    tmp_path: Path,
    capsys,
) -> None:
    run = tmp_path / "run"
    spec = {
        "mode": "corpus",
        "name": "cli-review",
        "target": {"minimum": 1, "preferred": 1, "maximum": 2},
        "scope": {"topics": {"include": ["evolutionary algorithm"]}},
        "delivery": {"profile": "generic"},
    }
    candidate = CandidateMetadata(
        "one",
        "Evolutionary Algorithm One",
        2025,
        "Test Venue",
        0.0,
        True,
        ("title", "abstract"),
        doi="10.1000/one",
        abstract="We develop an evolutionary algorithm.",
    )
    CorpusDiscoveryWorkflow(
        discoverer=lambda _: DiscoveryBatch(candidates=(candidate,))
    ).run(spec, run)
    packet = json.loads((run / "evidence-packets.jsonl").read_text(encoding="utf-8"))
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text(
        json.dumps(
            {
                "candidate_id": packet["candidate_id"],
                "evidence_hash": packet["evidence_hash"],
                "decision": "accept",
                "matched_topics": ["evolutionary algorithm"],
                "evidence_fields": ["title", "abstract"],
                "reason": "Title and abstract directly match the requested topic.",
                "reviewer": "codex",
                "rule_version": "corpus-semantic-v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
    )

    exit_code = run_cli(
        ["review", "corpus", "--run", str(run), "--decisions", str(decisions)],
        application=application,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "frozen"
    assert payload["accepted"] == 1
    assert payload["selected"] == 1
    assert Path(payload["selection_manifest"]).is_file()
    assert Path(payload["selected_papers"]).is_file()
