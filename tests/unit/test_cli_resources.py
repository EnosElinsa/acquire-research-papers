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
