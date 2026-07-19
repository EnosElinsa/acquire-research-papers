import json
from pathlib import Path

from acquire_research_papers.cli import Application, run_cli
from acquire_research_papers.research.workflow import ResearchWorkflow


def test_research_cli_plans_queries_and_writes_default_evidence_package(
    tmp_path: Path,
    capsys,
) -> None:
    brief = tmp_path / "brief.yaml"
    brief.write_text(
        """schema_version: 1
mode: research
question_type: gap-analysis
research_question: Does prior work optimize this coupling?
work_under_review:
  scenario: MEC
  mechanism: LLM-guided evolutionary computation
seed_papers: []
delivery:
  write_narrative: false
  export_markdown: false
""",
        encoding="utf-8",
    )
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        research_workflow=ResearchWorkflow(discoverer=lambda _: []),
    )
    output = tmp_path / "research-output"
    exit_code = run_cli(
        ["discover", "research", "--brief", str(brief), "--output", str(output)],
        application=application,
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "planned"
    assert payload["query_passes"] == 4
    for filename in (
        "research-manifest.csv",
        "pending-review.csv",
        "evidence-map.md",
        "nearest-work-matrix.csv",
        "gap-analysis.md",
        "research-plan.json",
    ):
        assert (output / filename).is_file()
    assert not (output / "narrative.md").exists()
