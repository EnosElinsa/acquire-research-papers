"""Build a fixed-wheel thin skill using an explicit public-asset allowlist."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path

NAME = "acquire-research-papers"
SCHEMA_FILES = (
    "corpus-spec.schema.json", "paper-record.schema.json", "research-brief.schema.json",
    "research-evidence-review.schema.json", "research-review-decision.schema.json",
    "institution-profile.schema.json", "library-plan.schema.json", "author-spec.schema.json",
    "author-discovery.schema.json", "library-audit.schema.json",
)
SKILL_FILES = (
    "SKILL.md", "agents/openai.yaml", "scripts/arp.py", "runtime.json",
    "references/corpus-mode.md", "references/research-mode.md", "references/source-policies.md",
    "references/credentials-and-cache.md", "references/workflows.md",
    "references/configuration.md", "references/library-mode.md", "references/author-mode.md",
    *("schemas/" + name for name in SCHEMA_FILES),
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_output(root: Path, output: Path, source: Path) -> None:
    if any(part.casefold() == ".git" for part in output.parts):
        raise ValueError("distribution output cannot be inside .git")
    if (output / ".git").exists() or (output / "skills" / NAME / ".git").exists():
        raise ValueError("distribution output cannot contain a .git checkout")
    if output == root or output == source or source in output.parents or output in source.parents:
        raise ValueError("distribution output cannot replace repository or source skill files")
    current = output
    while current != current.parent:
        if current.is_symlink():
            raise ValueError("distribution output cannot traverse symbolic links")
        current = current.parent


def _check_wheel(path: Path, version: str) -> None:
    expected = f"acquire_research_papers-{version}-py3-none-any.whl"
    if path.name != expected:
        raise ValueError("wheel filename does not match the project release version")
    with zipfile.ZipFile(path) as archive:
        metadata = archive.read(f"acquire_research_papers-{version}.dist-info/METADATA").decode("utf-8")
    if f"\nVersion: {version}\n" not in "\n" + metadata:
        raise ValueError("wheel metadata does not match the project release version")


def build(root: Path, output: Path, *, wheel: Path | None = None,
          update_source_manifest: bool = False) -> dict:
    root, output = root.resolve(), output.resolve()
    source = root / "skills" / NAME
    _safe_output(root, output, source)
    configuration = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = configuration["project"]["version"]
    output.mkdir(parents=True, exist_ok=True)
    if wheel is None:
        uv = shutil.which("uv")
        if not uv:
            raise ValueError("uv is required to build the runtime wheel")
        environment = dict(os.environ, SOURCE_DATE_EPOCH="1700000000")
        subprocess.run([uv, "build", "--wheel", "--out-dir", str(output)],
                       cwd=root, env=environment, check=True)
        wheel = output / f"acquire_research_papers-{version}-py3-none-any.whl"
    wheel = wheel.resolve()
    _check_wheel(wheel, version)
    manifest = {"schema_version": 1, "package": NAME, "version": version,
        "wheel": {"url": f"https://github.com/EnosElinsa/{NAME}/releases/download/v{version}/{wheel.name}",
                  "sha256": _hash(wheel)}}
    if update_source_manifest:
        (source / "runtime.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (source / "schemas").mkdir(parents=True, exist_ok=True)
        for name in SCHEMA_FILES:
            shutil.copyfile(root / "schemas" / name, source / "schemas" / name)
    destination = output / "skills" / NAME
    if destination.exists():
        if any(path.name.casefold() == ".git" for path in destination.rglob("*")):
            raise ValueError("skill destination cannot contain .git metadata")
        actual = {path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()}
        if actual - set(SKILL_FILES):
            raise ValueError("existing distribution contains unexpected files; choose a clean output directory")
    with tempfile.TemporaryDirectory(prefix="arp-skill-build-", dir=output) as temporary:
        stage = Path(temporary) / NAME
        for relative in SKILL_FILES:
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative == "runtime.json":
                target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            elif relative.startswith("schemas/"):
                shutil.copyfile(root / relative, target)
            else:
                asset = source / relative
                if asset.is_symlink() or not asset.is_file():
                    raise ValueError(f"required public skill asset is missing or linked: {relative}")
                shutil.copyfile(asset, target)
        destination.mkdir(parents=True, exist_ok=True)
        for relative in SKILL_FILES:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(stage / relative, target)
        zip_path = output / f"{NAME}-skill-{version}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for relative in sorted(SKILL_FILES):
                item = zipfile.ZipInfo(f"{NAME}/{relative}", date_time=(2023, 11, 14, 22, 13, 20))
                item.compress_type = zipfile.ZIP_DEFLATED
                item.external_attr = 0o644 << 16
                archive.writestr(item, (stage / relative).read_bytes())
    return {"version": version, "skill": str(destination), "zip": str(zip_path),
            "wheel": str(wheel), "wheel_sha256": manifest["wheel"]["sha256"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--update-source-manifest", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = build(args.root, args.output or args.root / "dist", wheel=args.wheel,
                       update_source_manifest=args.update_source_manifest)
    except (OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile, KeyError) as exc:
        parser.exit(1, f"Distribution build failed: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
