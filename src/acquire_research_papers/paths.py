from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir


@dataclass(frozen=True)
class ConfigPaths:
    root: Path
    settings: Path
    env_file: Path
    institutions: Path
    credentials: Path

    @classmethod
    def for_root(cls, root: Path) -> ConfigPaths:
        root = root.expanduser().resolve()
        return cls(root, root / "config.toml", root / ".env", root / "institutions",
                   root / "credentials")


@dataclass(frozen=True)
class AppPaths:
    registry: Path
    cache: Path
    secrets: Path
    profiles: Path
    dependencies: Path
    runs: Path
    config: Path

    @property
    def config_paths(self) -> ConfigPaths:
        return ConfigPaths.for_root(self.config)

    @classmethod
    def default(cls) -> AppPaths:
        if os.environ.get("ARP_DATA_ROOT"):
            return cls.for_root(Path(os.environ["ARP_DATA_ROOT"]).expanduser())
        legacy = Path(user_data_dir("Codex", appauthor=False))
        markers = (legacy / "paper-acquisition" / "registry.sqlite",
                   legacy / "secrets" / "acquire-research-papers" / "secrets.clixml",
                   legacy / "paper-acquisition" / "institutions")
        root = legacy if any(p.exists() for p in markers) else Path(
            user_data_dir("acquire-research-papers", appauthor=False))
        config = Path(os.environ.get("ARP_CONFIG_ROOT") or user_config_dir(
            "acquire-research-papers", appauthor=False)).expanduser()
        return cls.for_root(root, config_root=config)

    @classmethod
    def for_root(cls, local: Path, *, config_root: Path | None = None) -> AppPaths:
        root = local.resolve()
        config = Path(os.environ.get("ARP_CONFIG_ROOT") or config_root or root / "config")
        return cls(
            registry=root / "paper-acquisition" / "registry.sqlite",
            cache=root / "cache" / "acquire-research-papers",
            secrets=root / "secrets" / "acquire-research-papers",
            profiles=root / "browser-profiles" / "acquire-research-papers",
            dependencies=root / "deps" / "acquire-research-papers",
            runs=root / "paper-acquisition" / "runs",
            config=config.expanduser().resolve(),
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
