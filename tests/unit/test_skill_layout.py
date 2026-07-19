from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]


def test_required_skill_and_package_files_exist() -> None:
    required = [
        "SKILL.md",
        "agents/openai.yaml",
        "pyproject.toml",
        "src/acquire_research_papers/__init__.py",
        "src/acquire_research_papers/cli.py",
        "scripts/setup-sciencedirect-secret.ps1",
        "scripts/read-sciencedirect-credential.ps1",
        "scripts/sciencedirect-playwright.mjs",
    ]
    assert all((ROOT / relative).is_file() for relative in required)


def test_runtime_data_is_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "*.clixml", "registry.sqlite*", "runs/", "downloads/"):
        assert pattern in ignored


def test_sciencedirect_scau_contract_is_explicit() -> None:
    public_contract = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "SKILL.md",
            "references/source-policies.md",
            "references/credentials-and-cache.md",
        )
    )
    for required in (
        "sciencedirect_scau",
        "vpn.scau.edu.cn",
        "www-sciencedirect-com-s.vpn.scau.edu.cn",
        "CAPTCHA",
        "OTP",
        "atrust_required",
    ):
        assert required in public_contract
    assert "Do not store a campus account" not in public_contract


def test_release_version_is_synchronized_at_0_2_0() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_init = (ROOT / "src/acquire_research_papers/__init__.py").read_text(
        encoding="utf-8"
    )
    assert project["project"]["version"] == "0.2.0"
    assert '__version__ = "0.2.0"' in package_init
