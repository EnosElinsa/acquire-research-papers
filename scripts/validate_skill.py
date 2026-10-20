from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

import yaml

from build_distribution import NAME, SCHEMA_FILES, SKILL_FILES

PLACEHOLDERS = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b|\[TODO", re.IGNORECASE)


def parse_frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    try:
        _, frontmatter, _ = text.split("---", 2)
    except ValueError as exc:
        raise ValueError("SKILL.md frontmatter is not closed") from exc
    value = yaml.safe_load(frontmatter)
    if not isinstance(value, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    return value


def validate(root: Path) -> list[str]:
    root = root.resolve()
    repository = (root / "pyproject.toml").is_file() and (root / "src/acquire_research_papers").is_dir()
    skill = root / "skills" / NAME if repository else root
    errors = []
    if repository and (root / "SKILL.md").exists():
        errors.append("root SKILL.md duplicates the canonical nested skill")
    missing = [name for name in SKILL_FILES if not (skill / name).is_file()]
    if missing:
        errors.append("missing required skill files: " + ", ".join(missing))
    if (skill / "SKILL.md").is_file():
        try:
            metadata = parse_frontmatter(skill / "SKILL.md")
            if set(metadata) != {"name", "description"} or metadata.get("name") != NAME:
                errors.append("SKILL.md must contain the canonical name and description only")
            description = metadata.get("description")
            if not isinstance(description, str) or len(description.strip()) < 40:
                errors.append("skill description must be substantive")
        except (ValueError, OSError, yaml.YAMLError) as exc:
            errors.append(str(exc))
    if any(path.name.casefold() == ".git" for path in skill.rglob("*")):
        errors.append("skill directory cannot contain .git metadata")
    for forbidden in ("pyproject.toml", "uv.lock", "src", "tests", "node_modules"):
        if (skill / forbidden).exists():
            errors.append("developer content found in thin skill: " + forbidden)
    manifest_path = skill / "runtime.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            version = manifest.get("version", "")
            expected = (f"https://github.com/EnosElinsa/{NAME}/releases/download/v{version}/"
                        f"acquire_research_papers-{version}-py3-none-any.whl")
            if (manifest.get("schema_version") != 1 or manifest.get("package") != NAME
                    or not re.fullmatch(r"\d+\.\d+\.\d+", version)
                    or manifest.get("wheel", {}).get("url") != expected
                    or not re.fullmatch(r"[0-9a-f]{64}", manifest.get("wheel", {}).get("sha256", ""))):
                errors.append("runtime release manifest is invalid")
            if repository:
                config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
                if config["project"]["version"] != version:
                    errors.append("runtime manifest and Python package versions differ")
                includes = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
                if "scripts" in includes or "scripts/setup-ieee-profile-credential.ps1" not in includes:
                    errors.append("wheel runtime scripts must be explicitly allowlisted")
        except (ValueError, OSError, TypeError) as exc:
            errors.append("cannot parse release manifest: " + type(exc).__name__)
    for name in SCHEMA_FILES:
        path = skill / "schemas" / name
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or "$schema" not in value:
                errors.append("invalid public schema: " + name)
        except (ValueError, OSError):
            errors.append("invalid public schema: " + name)
        if repository and path.read_bytes() != (root / "schemas" / name).read_bytes():
            errors.append("skill schema snapshot differs from runtime schema: " + name)
    public = [skill / "SKILL.md", *(skill / "references").glob("*.md")]
    if repository:
        public.extend(root / name for name in (
            "README.md", "README.zh-CN.md", "SECURITY.md", "CONTRIBUTING.md"))
    for path in public:
        if path.is_file() and PLACEHOLDERS.search(path.read_text(encoding="utf-8")):
            errors.append("unfinished placeholder in " + str(path.relative_to(root)))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate repository or exported thin skill")
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    errors = validate(args.root)
    if errors:
        for error in errors:
            print("ERROR: " + error, file=sys.stderr)
        return 1
    print("Skill is valid!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
