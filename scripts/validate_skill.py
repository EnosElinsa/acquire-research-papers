from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml


EXPECTED_NAME = "acquire-research-papers"
REQUIRED_FILES = {
    "README.md",
    "README.zh-CN.md",
    "SECURITY.md",
    "SKILL.md",
    "agents/openai.yaml",
    "pyproject.toml",
    "schemas/corpus-spec.schema.json",
    "schemas/paper-record.schema.json",
    "schemas/research-brief.schema.json",
    "references/corpus-mode.md",
    "references/research-mode.md",
    "references/source-policies.md",
    "references/credentials-and-cache.md",
    "scripts/setup-secrets.ps1",
    "scripts/setup-ieee-institution.ps1",
    "scripts/update-ieee-institution-route.ps1",
    "scripts/setup-mineru-token.ps1",
    "scripts/read-institution-profile.ps1",
    "scripts/read-browser-credential.ps1",
    "scripts/setup-elsevier-api-key.ps1",
    "scripts/read-elsevier-api-key.ps1",
    "src/acquire_research_papers/acquisition/manual_handoff.py",
}
PLACEHOLDERS = ("TODO", "TBD", "FIXME", "XXX", "[TODO")


def parse_frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    try:
        _, frontmatter, _ = text.split("---", 2)
    except ValueError as exc:
        raise ValueError("SKILL.md frontmatter is not closed") from exc
    data = yaml.safe_load(frontmatter)
    if not isinstance(data, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    return data


def canonical_repository_name(root: Path) -> str:
    if root.name == EXPECTED_NAME:
        return root.name
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return root.name
    common_dir = Path(result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = (root / common_dir).resolve()
    return common_dir.parent.name


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    missing = sorted(relative for relative in REQUIRED_FILES if not (root / relative).is_file())
    if missing:
        errors.append(f"missing required files: {', '.join(missing)}")

    skill_path = root / "SKILL.md"
    if skill_path.is_file():
        try:
            metadata = parse_frontmatter(skill_path)
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            errors.append(str(exc))
        else:
            if set(metadata) != {"name", "description"}:
                errors.append("SKILL.md frontmatter may contain only name and description")
            if metadata.get("name") != EXPECTED_NAME:
                errors.append(f"skill name must be {EXPECTED_NAME!r}")
            description = metadata.get("description")
            if not isinstance(description, str) or len(description.strip()) < 40:
                errors.append("skill description must be a substantive string")

    repository_name = canonical_repository_name(root)
    if repository_name != EXPECTED_NAME:
        errors.append(
            f"repository folder must be named {EXPECTED_NAME!r}; found {repository_name!r}"
        )

    public_files = [
        root / "README.md",
        root / "README.zh-CN.md",
        root / "SECURITY.md",
        skill_path,
        *(root / "references").glob("*.md"),
    ]
    for path in public_files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        hit = next((marker for marker in PLACEHOLDERS if marker.casefold() in text.casefold()), None)
        if hit:
            errors.append(f"placeholder {hit!r} found in {path.relative_to(root)}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the acquire-research-papers skill")
    parser.add_argument("root", nargs="?", default=".", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    errors = validate(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Skill is valid!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
