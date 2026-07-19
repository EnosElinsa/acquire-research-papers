from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir


@dataclass(frozen=True)
class AppPaths:
    registry: Path
    cache: Path
    secrets: Path
    profiles: Path
    dependencies: Path
    runs: Path

    @classmethod
    def default(cls) -> AppPaths:
        local = Path(user_data_dir("Codex", appauthor=False))
        return cls.for_root(local)

    @classmethod
    def for_root(cls, local: Path) -> AppPaths:
        root = local.resolve()
        return cls(
            registry=root / "paper-acquisition" / "registry.sqlite",
            cache=root / "cache" / "acquire-research-papers",
            secrets=root / "secrets" / "acquire-research-papers",
            profiles=root / "browser-profiles" / "acquire-research-papers",
            dependencies=root / "deps" / "acquire-research-papers",
            runs=root / "paper-acquisition" / "runs",
        )

    def create_directories(self) -> None:
        directories = {
            self.registry.parent,
            self.cache,
            self.secrets,
            self.profiles,
            self.dependencies,
            self.runs,
        }
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


def ensure_outside_repository(candidate: Path, repository: Path) -> Path:
    resolved_candidate = candidate.resolve()
    resolved_repository = repository.resolve()
    if resolved_candidate == resolved_repository or resolved_repository in resolved_candidate.parents:
        raise ValueError("delivery and runtime paths must stay outside the skill repository")
    return resolved_candidate
