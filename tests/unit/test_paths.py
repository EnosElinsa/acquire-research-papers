from pathlib import Path

import pytest

from acquire_research_papers.paths import AppPaths, ensure_outside_repository


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
