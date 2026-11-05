import os
from pathlib import Path

import pytest

from acquire_research_papers.paths import AppPaths, ensure_outside_repository, resolve_path

windows_only = pytest.mark.skipif(os.name != "nt", reason="extended-length paths are Windows-only")


@windows_only
def test_resolve_path_drops_the_extended_length_prefix(tmp_path: Path) -> None:
    folder = tmp_path.resolve() / "Venue"
    folder.mkdir()
    assert resolve_path(Path("\\\\?\\" + str(folder))) == folder
    assert resolve_path(Path("\\\\?\\" + str(folder / "missing.pdf"))) == folder / "missing.pdf"


@windows_only
@pytest.mark.parametrize(("raw", "expected"), [
    ("\\\\?\\UNC\\server\\share\\a.pdf", "\\\\server\\share\\a.pdf"),
    ("\\\\?\\Volume{0}\\a.pdf", "\\\\?\\Volume{0}\\a.pdf"),
])
def test_resolve_path_shortens_unc_names_and_keeps_volume_names(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    monkeypatch.setattr(Path, "resolve", lambda self, strict=False: self)
    assert str(resolve_path(Path(raw))) == expected


def test_app_paths_are_outside_skill_repository(tmp_path: Path) -> None:
    paths = AppPaths.for_root(tmp_path / "local")
    assert paths.registry == tmp_path / "local" / "paper-acquisition" / "registry.sqlite"
    assert paths.cache == tmp_path / "local" / "cache" / "acquire-research-papers"
    assert paths.secrets == tmp_path / "local" / "secrets" / "acquire-research-papers"
    assert paths.profiles == tmp_path / "local" / "browser-profiles" / "acquire-research-papers"
    assert paths.dependencies == tmp_path / "local" / "deps" / "acquire-research-papers"
    assert paths.runs == tmp_path / "local" / "paper-acquisition" / "runs"


@pytest.mark.parametrize("relative", [".", "downloads", "nested/output"])
def test_delivery_cannot_target_skill_repository(tmp_path: Path, relative: str) -> None:
    repository = tmp_path / "skill"
    repository.mkdir()
    with pytest.raises(ValueError, match="outside the skill repository"):
        ensure_outside_repository(repository / relative, repository)


def test_delivery_may_target_sibling_directory(tmp_path: Path) -> None:
    repository = tmp_path / "skill"
    repository.mkdir()
    output = tmp_path / "paper-output"
    assert ensure_outside_repository(output, repository) == output.resolve()


def test_create_runtime_directories_excludes_registry_file(tmp_path: Path) -> None:
    paths = AppPaths.for_root(tmp_path / "local")
    paths.create_directories()
    assert paths.registry.parent.is_dir()
    assert not paths.registry.exists()
    assert all(
        directory.is_dir()
        for directory in (paths.cache, paths.secrets, paths.profiles, paths.dependencies, paths.runs)
    )
