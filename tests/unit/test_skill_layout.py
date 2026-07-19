from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_required_skill_and_package_files_exist() -> None:
    required = [
        "SKILL.md",
        "agents/openai.yaml",
        "pyproject.toml",
        "src/acquire_research_papers/__init__.py",
        "src/acquire_research_papers/cli.py",
    ]
    assert all((ROOT / relative).is_file() for relative in required)


def test_runtime_data_is_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "*.clixml", "registry.sqlite*", "runs/", "downloads/"):
        assert pattern in ignored
