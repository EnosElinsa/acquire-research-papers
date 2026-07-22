from pathlib import Path

from acquire_research_papers import cli


def test_runtime_script_root_falls_back_to_wheel_bundled_scripts(tmp_path: Path) -> None:
    package_root = tmp_path / "package"
    bundled = package_root / "_scripts"
    bundled.mkdir(parents=True)
    for name in (
        "ieee-playwright.mjs",
        "install-playwright.ps1",
        "read-browser-credential.ps1",
        "read-institution-profile.ps1",
        "read-mineru-token.ps1",
        "read-elsevier-api-key.ps1",
        "secret-store.ps1",
    ):
        (bundled / name).touch()

    assert hasattr(cli, "_resolve_script_root"), "wheel script resolver is not implemented"
    assert cli._resolve_script_root(tmp_path / "missing-repository", package_root) == bundled


def test_cli_exposes_separate_corpus_discovery_review_and_acquisition_phases() -> None:
    parser = cli.build_parser()

    discover = parser.parse_args(
        ["discover", "corpus", "--spec", "job.yaml", "--output", "run"]
    )
    review = parser.parse_args(
        ["review", "corpus", "--run", "run", "--decisions", "decisions.jsonl"]
    )
    acquire = parser.parse_args(
        ["acquire", "corpus", "--selection", "selection.json", "--output", "papers"]
    )

    assert (discover.command, discover.discover_mode) == ("discover", "corpus")
    assert (review.command, review.review_mode) == ("review", "corpus")
    assert (acquire.command, acquire.acquire_mode) == ("acquire", "corpus")
