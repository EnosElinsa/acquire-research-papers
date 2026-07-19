from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]


def test_required_skill_and_package_files_exist() -> None:
    required = [
        "README.md",
        "README.zh-CN.md",
        "SECURITY.md",
        "SKILL.md",
        "agents/openai.yaml",
        "pyproject.toml",
        "src/acquire_research_papers/__init__.py",
        "src/acquire_research_papers/cli.py",
        "src/acquire_research_papers/acquisition/manual_handoff.py",
        "scripts/setup-elsevier-api-key.ps1",
        "scripts/read-elsevier-api-key.ps1",
    ]
    assert all((ROOT / relative).is_file() for relative in required)


def test_runtime_data_is_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (
        "/docs/",
        ".env",
        "*.clixml",
        "registry.sqlite*",
        "runs/",
        "downloads/",
    ):
        assert pattern in ignored


def test_public_repository_metadata_is_complete() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = configuration["project"]
    assert project["readme"] == "README.md"
    assert "Topic :: Scientific/Engineering" in project["classifiers"]
    assert project["urls"]["Repository"].endswith("/acquire-research-papers")
    assert "pypdf>=6.14.2,<7" in project["dependencies"]
    force_include = configuration["tool"]["hatch"]["build"]["targets"]["wheel"][
        "force-include"
    ]
    assert force_include["scripts"] == "acquire_research_papers/_scripts"
    assert configuration["tool"]["hatch"]["build"]["exclude"] == ["/docs"]


def test_ci_covers_only_supported_browser_helper_with_minimal_permissions() -> None:
    workflow = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "tests/node/test-ieee-playwright.mjs" in workflow
    assert "test-sciencedirect-playwright" not in workflow


def test_sciencedirect_manual_handoff_contract_is_explicit() -> None:
    public_contract = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "SKILL.md",
            "references/source-policies.md",
            "README.md",
            "README.zh-CN.md",
        )
    )
    for required in (
        "manual-fetch",
        "manual_publisher_download",
        "publisher's raw BibTeX",
        "正常 Chrome",
        "Cookie",
    ):
        assert required in public_contract
    for forbidden in (
        "setup-sciencedirect-secret.ps1",
        "sciencedirect-playwright.mjs",
        "www-sciencedirect-com-s.vpn.scau.edu.cn",
        "unattended South China Agricultural University ScienceDirect access",
    ):
        assert forbidden not in public_contract


def test_retired_sciencedirect_website_automation_is_not_distributed() -> None:
    obsolete = (
        "scripts/sciencedirect-playwright.mjs",
        "scripts/setup-sciencedirect-secret.ps1",
        "scripts/read-sciencedirect-credential.ps1",
        "src/acquire_research_papers/acquisition/adapters/sciencedirect_bridge.py",
        "tests/node/test-sciencedirect-playwright.mjs",
        "tests/unit/test_sciencedirect_bridge.py",
    )
    assert all(not (ROOT / relative).exists() for relative in obsolete)


def test_release_version_is_synchronized_at_0_2_0() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_init = (ROOT / "src/acquire_research_papers/__init__.py").read_text(
        encoding="utf-8"
    )
    assert project["project"]["version"] == "0.2.0"
    assert '__version__ = "0.2.0"' in package_init
