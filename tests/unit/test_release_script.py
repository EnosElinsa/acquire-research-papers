from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

COPIED = ("pyproject.toml", "CITATION.cff", "src/acquire_research_papers/__init__.py", "uv.lock",
          "tests/test_distribution.py", "tests/unit/test_host_installer.py",
          "tests/unit/test_skill_layout.py", "README.md", "README.zh-CN.md")


def repository_copy(tmp_path: Path, newline: str = "\n") -> tuple[Path, str]:
    root = tmp_path / "repo"
    for relative in COPIED:
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, root / relative)
    old = release.current_version(root)
    changelog = f"# Changelog\n\n## Unreleased\n\n- New thing.\n\n## {old} \u2014 2026-11-04\n"
    (root / "CHANGELOG.md").write_bytes(changelog.replace("\n", newline).encode("utf-8"))
    with (root / "README.md").open("ab") as handle:
        handle.write(f"\nHistory: the queue arrived in {old}.\n".encode())
    return root, old


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_bump_keeps_the_changelog_line_endings(tmp_path, newline):
    root, old = repository_copy(tmp_path, newline)
    new = f"{int(old.split('.')[0]) + 1}.0.0"

    release.bump(root, new, today="2026-12-01")

    changelog = (root / "CHANGELOG.md").read_bytes().decode("utf-8")
    assert f"## {new} \u2014 2026-12-01{newline}" in changelog
    assert changelog.count(newline) == 7


def test_bump_rewrites_every_pin_and_leaves_history_alone(tmp_path):
    root, old = repository_copy(tmp_path)
    major = int(old.split(".")[0])
    new = f"{major + 1}.0.0"

    result = release.bump(root, new, today="2026-12-01")

    assert (result["from"], result["to"]) == (old, new)
    assert release.current_version(root) == new
    citation = (root / "CITATION.cff").read_text(encoding="utf-8")
    assert f"\nversion: {new}\n" in citation and '\ndate-released: "2026-12-01"\n' in citation
    assert f'__version__ = "{new}"' in (root / "src/acquire_research_papers/__init__.py").read_text()
    lock = (root / "uv.lock").read_text(encoding="utf-8")
    assert f'name = "acquire-research-papers"\nversion = "{new}"' in lock
    for relative in release._FIXTURE_FILES:
        assert old not in (root / relative).read_text(encoding="utf-8"), relative
    layout = (root / "tests/unit/test_skill_layout.py").read_text(encoding="utf-8")
    assert "synchronized_at_" + new.replace(".", "_") in layout
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert f"releases/tag/v{new}" in readme and f"History: the queue arrived in {old}." in readme
    assert f"releases/tag/v{new}" in (root / "README.zh-CN.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_bytes().decode("utf-8")
    assert changelog.startswith(f"# Changelog\n\n## {new} \u2014 2026-12-01\n")
    assert f"## {old} \u2014 2026-11-04" in changelog


@pytest.mark.parametrize("problem", ["no-unreleased", "not-greater", "bad-date"])
def test_a_failed_bump_writes_nothing(tmp_path, problem):
    root, old = repository_copy(tmp_path)
    new = f"{int(old.split('.')[0]) + 1}.0.0"
    day = "2026-12-01"
    if problem == "no-unreleased":
        (root / "CHANGELOG.md").write_text("# Changelog\n\n## 0.1.0 \u2014 2020-01-01\n",
                                           encoding="utf-8")
    elif problem == "not-greater":
        new = old
    else:
        day = "1 December"
    before = {relative: (root / relative).read_bytes() for relative in COPIED}

    with pytest.raises(release.ReleaseError):
        release.bump(root, new, today=day)

    assert {relative: (root / relative).read_bytes() for relative in COPIED} == before


def fake_build_root(tmp_path: Path, version: str = "1.2.3") -> Path:
    root = tmp_path / "repo"
    (root / "skills/acquire-research-papers").mkdir(parents=True)
    (root / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n', encoding="utf-8")
    for readme in ("README.md", "README.zh-CN.md"):
        (root / readme).write_text(f"See releases/tag/v{version}.\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(f"# Changelog\n\n## {version} \u2014 2026-12-01\n",
                                       encoding="utf-8")
    return root


def fake_wheel(path: Path, readme: str, extra: bytes = b"") -> None:
    with zipfile.ZipFile(path, "w") as wheel:  # fixed dates, so equal input gives equal bytes
        wheel.writestr(zipfile.ZipInfo("pkg-1.dist-info/METADATA", (1980, 1, 1, 0, 0, 0)),
                       "Name: pkg\n\n" + readme)
        wheel.writestr(zipfile.ZipInfo("pkg/data", (1980, 1, 1, 0, 0, 0)), b"wheel" + extra)


def fake_builder(drift: bool = False):
    calls = []

    def builder(root: Path, output: Path, *, update_source_manifest: bool) -> dict:
        calls.append(update_source_manifest)
        version = release.current_version(root)
        wheel, archive = release._asset_names(version)
        output.mkdir(parents=True)
        fake_wheel(output / wheel, (root / "README.md").read_text(encoding="utf-8"),
                   bytes([len(calls)]) if drift else b"")
        (output / archive).write_bytes(b"zip")
        if update_source_manifest:
            (root / "skills/acquire-research-papers/runtime.json").write_text(json.dumps({
                "version": version,
                "wheel": {"sha256": hashlib.sha256((output / wheel).read_bytes()).hexdigest()}}))
        return {}

    return builder, calls


def test_build_checks_a_second_build_and_writes_sha256sums(tmp_path):
    root = fake_build_root(tmp_path)
    builder, calls = fake_builder()

    result = release.build_release(root, builder=builder)

    assert calls == [True, False]
    dist = root / "dist/release-1.2.3"
    wheel = (dist / "acquire_research_papers-1.2.3-py3-none-any.whl").read_bytes()
    assert (dist / "SHA256SUMS").read_bytes() == (
        f"{hashlib.sha256(wheel).hexdigest()}  acquire_research_papers-1.2.3-py3-none-any.whl\n"
        f"{hashlib.sha256(b'zip').hexdigest()}  acquire-research-papers-skill-1.2.3.zip\n"
    ).encode()
    assert result["reproducible"] is True
    with pytest.raises(release.ReleaseError, match="already exists"):
        release.build_release(root, builder=builder)


@pytest.mark.parametrize(("lost", "message"), [
    ("README.zh-CN.md", "README.zh-CN.md does not link releases/tag/v1.2.3"),
    ("CHANGELOG.md", "CHANGELOG.md has no 1.2.3 section"),
    ("wheel", "built wheel's README does not link"),
])
def test_build_refuses_when_the_bump_text_is_missing(tmp_path, lost, message):
    # At 0.14.0 the bump's README and CHANGELOG edits vanished before the first build.
    root = fake_build_root(tmp_path)
    builder, _ = fake_builder()
    if lost == "wheel":
        def builder(root, output, *, update_source_manifest, inner=builder):
            result = inner(root, output, update_source_manifest=update_source_manifest)
            wheel = output / release._asset_names("1.2.3")[0]
            fake_wheel(wheel, "See releases/tag/v1.2.2.\n")
            if update_source_manifest:
                (root / "skills/acquire-research-papers/runtime.json").write_text(json.dumps({
                    "version": "1.2.3",
                    "wheel": {"sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}}))
            return result
    else:
        (root / lost).write_text("# old text from before the bump\n", encoding="utf-8")

    with pytest.raises(release.ReleaseError, match=message):
        release.build_release(root, builder=builder)
    assert not (root / "dist/release-1.2.3/SHA256SUMS").exists()


def test_build_rejects_a_build_that_is_not_reproducible(tmp_path):
    root = fake_build_root(tmp_path)
    builder, _ = fake_builder(drift=True)

    with pytest.raises(release.ReleaseError, match="different bytes"):
        release.build_release(root, builder=builder)
    assert not (root / "dist/release-1.2.3/SHA256SUMS").exists()


class FakeGitHub:
    """Answers the git and gh commands of publish; the first wheel upload drops its connection."""

    HEAD = "a" * 40

    def __init__(self, *, remote_main: str = HEAD, published: bool = False,
                 ci: tuple[tuple[str, str | None], ...] = (("completed", "success"),
                                                           ("completed", "success"))):
        self.commands: list[list[str]] = []
        self.remote_main = remote_main
        self.ci = [{"databaseId": index, "status": status, "conclusion": conclusion,
                    "headBranch": "main" if index == 0 else "v1.2.3"}
                   for index, (status, conclusion) in enumerate(ci)]
        self.release: dict | None = (
            {"tag_name": "v1.2.3", "draft": False, "assets": []} if published else None)
        self.upload_failures = {"acquire_research_papers-1.2.3-py3-none-any.whl": 1}

    def __call__(self, command):
        command = list(command)
        self.commands.append(command)

        def done(stdout: str = "", code: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(command, code, stdout, stderr)

        if command[:2] == ["git", "status"]:
            return done("")
        if command[:2] == ["git", "rev-parse"]:
            return done(self.HEAD + "\n")
        if command[:2] == ["git", "ls-remote"]:
            return done(f"{self.remote_main}\trefs/heads/main\n{self.HEAD}\trefs/tags/v1.2.3^{{}}\n")
        if command[:2] == ["gh", "api"]:
            return done(json.dumps([self.release] if self.release else []))
        if command[:3] == ["gh", "run", "list"]:
            assert command[command.index("--commit") + 1] == self.HEAD
            return done(json.dumps(self.ci))
        if command[:3] == ["gh", "release", "create"]:
            assert "--draft" in command
            self.release = {"tag_name": "v1.2.3", "draft": True, "assets": []}
            return done("https://github.com/x/y/releases/tag/untagged-1\n")
        if command[:3] == ["gh", "release", "upload"]:
            path = Path(command[4])
            if self.upload_failures.get(path.name):
                self.upload_failures[path.name] -= 1
                return done(code=1, stderr=f'Post "https://uploads.github.com/{path.name}": EOF')
            self.release["assets"] = [asset for asset in self.release["assets"]
                                      if asset["name"] != path.name]
            self.release["assets"].append({"name": path.name, "size": path.stat().st_size,
                                           "state": "uploaded", "source": str(path)})
            return done()
        if command[:3] == ["gh", "release", "edit"]:
            self.release["draft"] = False
            return done()
        if command[:3] == ["gh", "release", "download"]:
            target = Path(command[command.index("--dir") + 1])
            for asset in self.release["assets"]:
                shutil.copyfile(asset["source"], target / asset["name"])
            return done()
        raise AssertionError(f"unexpected command {command}")


def built_release(tmp_path: Path) -> tuple[Path, Path]:
    root = fake_build_root(tmp_path)
    builder, _ = fake_builder()
    release.build_release(root, builder=builder)
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n", encoding="utf-8")
    return root, notes


def test_publish_uploads_with_retries_publishes_the_draft_and_compares_downloads(tmp_path):
    root, notes = built_release(tmp_path)
    github = FakeGitHub()
    sleeps = []

    result = release.publish(root, title="v1.2.3 \u2014 Test", notes_file=notes,
                             repository="x/y", runner=github, sleeper=sleeps.append)

    assert result["status"] == "published" and result["published_assets_match"] is True
    assert result["upload_attempts"] == {
        "acquire_research_papers-1.2.3-py3-none-any.whl": 2,
        "acquire-research-papers-skill-1.2.3.zip": 1, "SHA256SUMS": 1}
    assert sleeps == [release.RETRY_SECONDS]
    gh = [command[:3] for command in github.commands if command[0] == "gh"]
    assert gh.index(["gh", "release", "create"]) < gh.index(["gh", "release", "edit"])
    assert gh[-1] == ["gh", "release", "download"]
    edit = next(command for command in github.commands if command[:3] == ["gh", "release", "edit"])
    assert "--draft=false" in edit


def test_publish_stops_before_github_when_main_was_not_pushed(tmp_path):
    root, notes = built_release(tmp_path)
    github = FakeGitHub(remote_main="b" * 40)

    with pytest.raises(release.ReleaseError, match="push main again"):
        release.publish(root, title="t", notes_file=notes, repository="x/y", runner=github,
                        sleeper=lambda seconds: None)
    assert not any(command[0] == "gh" for command in github.commands)


@pytest.mark.parametrize(("ci", "message"), [
    ((("completed", "success"), ("in_progress", None)), "CI is still running"),
    ((("completed", "failure"),), "ended failure"),
    ((), "no test workflow run"),
])
def test_publish_waits_for_passed_ci_on_the_release_commit(tmp_path, ci, message):
    root, notes = built_release(tmp_path)
    github = FakeGitHub(ci=ci)

    with pytest.raises(release.ReleaseError, match=message):
        release.publish(root, title="t", notes_file=notes, repository="x/y", runner=github,
                        sleeper=lambda seconds: None)
    assert not any(command[:2] == ["gh", "release"] for command in github.commands)


def test_publish_refuses_a_published_release_and_changed_assets(tmp_path):
    root, notes = built_release(tmp_path)
    with pytest.raises(release.ReleaseError, match="already published"):
        release.publish(root, title="t", notes_file=notes, repository="x/y",
                        runner=FakeGitHub(published=True), sleeper=lambda seconds: None)

    (root / "dist/release-1.2.3/acquire-research-papers-skill-1.2.3.zip").write_bytes(b"changed")
    with pytest.raises(release.ReleaseError, match="SHA256SUMS does not match"):
        release.publish(root, title="t", notes_file=notes, repository="x/y",
                        runner=FakeGitHub(), sleeper=lambda seconds: None)
