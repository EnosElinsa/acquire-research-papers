import re
import subprocess
import sys
from pathlib import Path

from acquire_research_papers.specs import load_corpus_spec, load_research_brief


ROOT = Path(__file__).resolve().parents[2]


def tracked_files() -> list[str]:
    return subprocess.check_output(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).splitlines()


def test_repository_contains_no_runtime_or_delivery_artifacts() -> None:
    forbidden_suffixes = {".clixml", ".sqlite", ".pdf", ".bib", ".docx"}
    forbidden_parts = {
        "node_modules",
        ".venv",
        "browser-profiles",
        "downloads",
        "runs",
    }
    tracked = tracked_files()
    assert not [path for path in tracked if Path(path).suffix.casefold() in forbidden_suffixes]
    assert not [path for path in tracked if forbidden_parts.intersection(Path(path).parts)]
    approved_design_docs = {
        "docs/superpowers/plans/2026-10-20-portable-composable-research-workflows.md",
        "docs/portable-workflows-progress.md",
        "docs/superpowers/plans/2026-07-25-discovery-api-credentials-implementation.md",
        "docs/superpowers/specs/2026-07-25-discovery-api-credentials-design.md",
    }
    tracked_docs = {path for path in tracked if "docs" in Path(path).parts}
    assert tracked_docs <= approved_design_docs


def test_skill_routes_all_three_modes_and_explicit_markdown_policy() -> None:
    text = (ROOT / "skills/acquire-research-papers/SKILL.md").read_text(encoding="utf-8")
    assert "fetch" in text
    assert "discover corpus" in text
    assert "discover research" in text
    assert "Markdown" in text and "explicit" in text
    assert "manual-download.csv" in text
    assert "institution profile" in text
    assert len(text.splitlines()) < 500


def test_skill_documents_two_stage_corpus_contract() -> None:
    text = (ROOT / "skills/acquire-research-papers/SKILL.md").read_text(encoding="utf-8")
    assert "arp discover corpus" in text
    assert "arp acquire corpus" in text
    assert "selected-papers.jsonl" in text
    assert "manual-download.csv" in text
    assert "--defer-host" in text
    assert "Auto-acquire only high-confidence matches" not in text


def test_progressive_disclosure_references_exist() -> None:
    required = {
        "corpus-mode.md",
        "research-mode.md",
        "source-policies.md",
        "credentials-and-cache.md",
    }
    reference_root = ROOT / "skills/acquire-research-papers/references"
    assert required <= {path.name for path in reference_root.glob("*.md")}


def test_public_documentation_is_present_and_has_no_placeholders() -> None:
    public_files = [
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        ROOT / "SECURITY.md",
        ROOT / "skills/acquire-research-papers/SKILL.md",
        *(ROOT / "skills/acquire-research-papers/references").glob("*.md"),
    ]
    assert all(path.is_file() for path in public_files)
    placeholder = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b|\[TODO", re.IGNORECASE)
    assert not [path for path in public_files if placeholder.search(path.read_text(encoding="utf-8"))]


def test_readmes_explain_the_user_journey_and_current_maturity() -> None:
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    english_sections = {
        "## Choose the workflow",
        "## First use: configure only what this task needs",
        "## How corpus discovery actually works",
        "## How literature research actually works",
        "## Source support and maturity",
        "## Accuracy and trust boundaries",
        "## Current limitations",
        "## Roadmap",
    }
    chinese_sections = {
        "## 选择适合的工作流",
        "## 首次使用：只配置当前任务需要的能力",
        "## 论文集检索实际如何工作",
        "## 文献调研实际如何工作",
        "## 来源支持与成熟度",
        "## 准确性与可信边界",
        "## 当前限制",
        "## 后续路线图",
    }
    assert english_sections <= set(english.splitlines())
    assert chinese_sections <= set(chinese.splitlines())

    shared_contracts = (
        "arp config status",
        "pending_abstract",
        "ready_unreviewed",
        "manual-download.csv",
        "Crossref",
        "OpenAlex",
        "Semantic Scholar",
        "ScienceDirect",
        "ACM",
        "IEEE",
        "MinerU",
    )
    for contract in shared_contracts:
        assert contract in english
        assert contract in chinese

    assert "status: review_required" in english
    assert "status: review_required" in chinese
    for command in (
        "review research",
        "acquire research",
        "evidence research",
        "citation-graph.json",
        "claim-coverage.csv",
    ):
        assert command in english
        assert command in chinese
    assert "live-tested end to end with one CARSI institution" in english
    assert "已在一个 CARSI 院校完成端到端真实验证" in chinese
    assert "does not prove live API or publisher entitlement" in english
    assert "不代表远端 API 或出版社权限一定可用" in chinese
    assert "precision/recall" in english
    assert "precision/recall" in chinese


def test_readme_yaml_examples_are_copyable_specs(tmp_path: Path) -> None:
    for readme_name in ("README.md", "README.zh-CN.md"):
        text = (ROOT / readme_name).read_text(encoding="utf-8")
        yaml_blocks = re.findall(r"```yaml\n(.*?)\n```", text, flags=re.DOTALL)
        assert len(yaml_blocks) == 2

        corpus_path = tmp_path / f"{readme_name}-corpus.yaml"
        research_path = tmp_path / f"{readme_name}-research.yaml"
        corpus_path.write_text(yaml_blocks[0], encoding="utf-8")
        research_path.write_text(yaml_blocks[1], encoding="utf-8")

        assert load_corpus_spec(corpus_path)["mode"] == "corpus"
        assert load_research_brief(research_path)["mode"] == "research"


def test_tracked_text_contains_no_jwt_or_private_key() -> None:
    jwt = re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")
    private_key = "-----BEGIN " + "PRIVATE KEY-----"
    offenders = []
    for relative in tracked_files():
        path = ROOT / relative
        if not path.is_file() or path.suffix.casefold() in {".png", ".jpg", ".zip"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if jwt.search(text) or private_key in text:
            offenders.append(relative)
    assert not offenders


def test_bundled_skill_validator_accepts_repository() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_skill.py"), str(ROOT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr or result.stdout
