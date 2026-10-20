"""Copy a built thin skill safely, preserving any developer checkout and prior install."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path

from build_distribution import SKILL_FILES

HOST_DIRECTORIES = {
    "codex": ".agents", "claude-code": ".claude",
    "kiro-ide": ".kiro", "kiro-cli": ".kiro",
}


def _git_or_link(path: Path) -> None:
    for current in (path, *path.parents):
        if current.name.casefold() == ".git" or (current / ".git").exists():
            raise ValueError("installation target is inside a git checkout; preserve it and choose a new directory")
        if current.is_symlink():
            raise ValueError("installation paths cannot traverse symbolic links")
    if path.is_dir() and any(item.name.casefold() == ".git" for item in path.rglob("*")):
        raise ValueError("installation target contains git metadata")


def _validate_tree(path: Path) -> dict[str, str]:
    if not path.is_dir():
        raise ValueError("skill source must be an exported skill directory")
    actual = {}
    for item in path.rglob("*"):
        if item.is_symlink():
            raise ValueError("thin skill cannot contain symbolic links")
        if item.is_file():
            relative = item.relative_to(path).as_posix()
            actual[relative] = hashlib.sha256(item.read_bytes()).hexdigest()
    if set(actual) != set(SKILL_FILES):
        raise ValueError("skill tree differs from the explicit public-asset allowlist")
    manifest = json.loads((path / "runtime.json").read_text(encoding="utf-8"))
    if manifest.get("package") != "acquire-research-papers" or manifest.get("schema_version") != 1:
        raise ValueError("unsupported skill runtime manifest")
    return actual


def install(source: Path, target: Path, *, replace: bool = False) -> dict:
    source = source.absolute()
    target = target.absolute()
    _git_or_link(target)
    source = source.resolve()
    target = target.resolve()
    if target == source or source in target.parents or target in source.parents:
        raise ValueError("installation source and target directories must not overlap")
    expected = _validate_tree(source)
    if target.exists():
        if not replace:
            raise ValueError("target already exists; use --replace only for a clean prior thin skill")
        _validate_tree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    with tempfile.TemporaryDirectory(prefix="arp-skill-install-", dir=target.parent) as temporary:
        stage = Path(temporary) / "skill"
        stage.mkdir()
        for relative in SKILL_FILES:
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, destination)
        if _validate_tree(stage) != expected or _validate_tree(source) != expected:
            raise ValueError("skill source changed during installation")
        _git_or_link(target)
        if target.exists():
            if not replace:
                raise ValueError("target appeared during installation; refusing replacement")
            _validate_tree(target)
            backup = target.with_name(target.name + ".previous-" + uuid.uuid4().hex[:12])
            target.rename(backup)
        try:
            stage.rename(target)
        except OSError:
            if backup is not None and not target.exists():
                backup.rename(target)
            raise
    return {"status": "installed", "target": str(target),
            "backup": str(backup) if backup is not None else None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--target", type=Path)
    destination.add_argument("--host", choices=tuple(HOST_DIRECTORIES))
    parser.add_argument("--project-root", type=Path,
                        help="select a project skill directory with --host")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    if args.project_root and not args.host:
        parser.error("--project-root requires --host")
    target = args.target or (args.project_root or Path.home()) / HOST_DIRECTORIES[args.host] / (
        "skills") / "acquire-research-papers"
    try:
        result = install(args.source, target, replace=args.replace)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Skill installation failed: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
