"""Maintainer release steps: bump the version, build checked assets, and publish them.

  python scripts/release.py bump 0.13.0
  python scripts/release.py build
  python scripts/release.py smoke            # live checks of the built ZIP and wheel
  python scripts/release.py publish --title "v0.13.0 — …" --notes-file notes.md
  python scripts/release.py smoke --public   # the same checks from the public release URL
  python scripts/release.py remote --host user@host   # install on a remote host over SSH
  python scripts/release.py checksums <dir>           # SHA256SUMS for a rebuilt wheel and ZIP
  python scripts/release.py compare <dir> <dir> ...   # byte-identical assets, or exit 1

``bump`` rewrites every version string in one pass and changes nothing if any file is not as
expected. ``build`` builds the wheel and skill ZIP, rebuilds them in a temporary directory to
prove they are byte-reproducible, and writes ``SHA256SUMS``. ``publish`` checks that the
release commit and tag are pushed and that every test workflow run for that commit passed,
creates a draft release, uploads each asset with retries
(GitHub's upload host sometimes drops a connection), checks the uploaded sizes, publishes the
draft, and downloads the assets again to compare hashes. ``remote`` installs the built skill
ZIP into ``~/.kiro/skills`` and ``~/.codex/skills`` on a host given at run time, after backing
up the installed skill (see ``release_remote.py``). ``checksums`` and ``compare`` serve the
release provenance workflow, which rebuilds a tag on Linux and Windows and compares the
rebuilds with each other and with the published assets before attesting them. Committing,
tagging, and pushing stay manual. Every step prints one JSON object.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import time
import tomllib
import zipfile
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "EnosElinsa/acquire-research-papers"
NAME = "acquire-research-papers"
_VERSION = re.compile(r"\d+\.\d+\.\d+")
# Files whose every occurrence of the old version is a release pin (test fixtures).
_FIXTURE_FILES = ("tests/test_distribution.py", "tests/unit/test_host_installer.py",
                  "tests/unit/test_skill_layout.py")
# README sections that name the current release; versions elsewhere in a README are history.
_README_SECTIONS = {"README.md": "### Release downloads and manual installation",
                    "README.zh-CN.md": "### \u53d1\u5e03\u6587\u4ef6\u4e0e\u624b\u52a8\u5b89\u88c5"}
UPLOAD_ATTEMPTS = 5
RETRY_SECONDS = 10.0


class ReleaseError(RuntimeError):
    """A release precondition or step failed; nothing after it ran."""


def _version_tuple(value: str) -> tuple[int, ...]:
    if not _VERSION.fullmatch(value):
        raise ReleaseError(f"version must look like 1.2.3, got {value!r}")
    return tuple(int(part) for part in value.split("."))


def current_version(root: Path) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _replace_exactly(text: str, old: str, new: str, count: int, where: str) -> str:
    found = text.count(old)
    if found != count:
        raise ReleaseError(f"{where}: expected {count} occurrence(s) of {old!r}, found {found}")
    return text.replace(old, new)


def _substitute_exactly(text: str, pattern: str, replacement: str, where: str) -> str:
    """Replace the single match of ``pattern``; line endings inside it are kept as found."""
    result, found = re.subn(pattern, replacement, text)
    if found != 1:
        raise ReleaseError(f"{where}: expected one match of {pattern!r}, found {found}")
    return result


def _replace_in_section(text: str, heading: str, old: str, new: str, where: str) -> tuple[str, int]:
    match = re.search(rf"^{re.escape(heading)}\r?\n", text, flags=re.MULTILINE)
    if match is None:
        raise ReleaseError(f"{where}: section {heading!r} not found")
    body = match.end()
    following = re.search(r"^#", text[body:], flags=re.MULTILINE)
    end = body + following.start() if following else len(text)
    section = text[body:end]
    found = section.count(old)
    if not found:
        raise ReleaseError(f"{where}: the release section does not name {old}")
    return text[:body] + section.replace(old, new) + text[end:], found


def bump(root: Path, new: str, *, today: str | None = None) -> dict:
    """Rewrite every version string from the current version to ``new``, all or nothing."""
    old = current_version(root)
    if _version_tuple(new) <= _version_tuple(old):
        raise ReleaseError(f"new version {new} must be greater than the current {old}")
    day = today or date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ReleaseError(f"release date must look like 2026-11-04, got {day!r}")
    changes: dict[str, str] = {}
    counts: dict[str, int] = {}

    def stage(relative: str, text: str, count: int) -> None:
        changes[relative], counts[relative] = text, count

    stage("pyproject.toml", _replace_exactly(_read(root / "pyproject.toml"), f'version = "{old}"',
                                             f'version = "{new}"', 1, "pyproject.toml"), 1)
    citation = _substitute_exactly(_read(root / "CITATION.cff"),
                                   rf"(?m)^version: {re.escape(old)}(\r?)$",
                                   f"version: {new}\\g<1>", "CITATION.cff")
    stage("CITATION.cff", _substitute_exactly(citation, r'(?m)^date-released: "[\d-]+"(\r?)$',
                                              f'date-released: "{day}"\\g<1>', "CITATION.cff"), 2)
    init = "src/acquire_research_papers/__init__.py"
    stage(init, _replace_exactly(_read(root / init), f'__version__ = "{old}"',
                                 f'__version__ = "{new}"', 1, init), 1)
    stage("uv.lock", _substitute_exactly(
        _read(root / "uv.lock"), rf'(name = "{re.escape(NAME)}"\r?\nversion = "){re.escape(old)}"',
        rf'\g<1>{new}"', "uv.lock"), 1)
    for relative in _FIXTURE_FILES:
        text = _read(root / relative)
        found = text.count(old)
        if not found:
            raise ReleaseError(f"{relative}: no occurrence of {old}")
        text = text.replace(old, new).replace(
            "synchronized_at_" + old.replace(".", "_"), "synchronized_at_" + new.replace(".", "_"))
        stage(relative, text, found)
    for relative, heading in _README_SECTIONS.items():
        text, found = _replace_in_section(_read(root / relative), heading, old, new, relative)
        stage(relative, text, found)
    changelog = _read(root / "CHANGELOG.md")
    if re.search(rf"(?m)^## {re.escape(new)} ", changelog):
        raise ReleaseError(f"CHANGELOG.md already has a {new} section")
    stage("CHANGELOG.md", _substitute_exactly(changelog, r"(?m)^## Unreleased(\r?)$",
                                              f"## {new} \u2014 {day}\\g<1>", "CHANGELOG.md"), 1)
    for relative, text in changes.items():  # nothing is written until every file checked out
        (root / relative).write_bytes(text.encode("utf-8"))
    return {"status": "bumped", "from": old, "to": new, "date": day, "replacements": counts,
            "next_action": "Run python scripts/release.py build, then the tests and "
                           "validate_skill.py; runtime.json pins the new wheel only after build."}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _asset_names(version: str) -> tuple[str, str]:
    return (f"acquire_research_papers-{version}-py3-none-any.whl",
            f"{NAME}-skill-{version}.zip")


_WHEEL_NAME = re.compile(r"acquire_research_papers-(\d+\.\d+\.\d+)-py3-none-any\.whl")
_ZIP_NAME = re.compile(rf"{re.escape(NAME)}-skill-(\d+\.\d+\.\d+)\.zip")


def _sums_text(hashes: dict[str, str], names: Sequence[str]) -> str:
    return "".join(f"{hashes[name]}  {name}\n" for name in names)  # LF lines, wheel first


def _release_assets(directory: Path, version: str | None = None) -> tuple[str, dict[str, str]]:
    """The version and wheel/ZIP hashes in one asset directory.

    A SHA256SUMS file beside them, when present, must list exactly those hashes.
    """
    if not directory.is_dir():
        raise ReleaseError(f"{directory} is not a directory")
    wheels = sorted(path.name for path in directory.iterdir() if _WHEEL_NAME.fullmatch(path.name))
    zips = sorted(path.name for path in directory.iterdir() if _ZIP_NAME.fullmatch(path.name))
    if len(wheels) != 1 or len(zips) != 1:
        raise ReleaseError(f"{directory} must hold exactly one release wheel and one skill ZIP; "
                           f"found {wheels + zips or 'neither'}")
    found = wheels[0].split("-")[1]
    if zips[0] != f"{NAME}-skill-{found}.zip":
        raise ReleaseError(f"{directory} holds a wheel and a ZIP of different versions")
    if version is not None and found != version:
        raise ReleaseError(f"{directory} holds version {found}, expected {version}")
    names = _asset_names(found)
    hashes = {name: _sha256(directory / name) for name in names}
    sums = directory / "SHA256SUMS"
    if sums.is_file() and sums.read_bytes() != _sums_text(hashes, names).encode("ascii"):
        raise ReleaseError(f"{sums} does not list the hashes of the wheel and ZIP beside it")
    return found, hashes


def write_checksums(directory: Path) -> dict:
    """Write SHA256SUMS for the wheel and ZIP in a directory, as build does."""
    directory = directory.resolve()
    sums = directory / "SHA256SUMS"
    if sums.exists():
        raise ReleaseError(f"{sums} already exists")
    version, hashes = _release_assets(directory)
    wheel, skill_zip = _asset_names(version)
    sums.write_bytes(_sums_text(hashes, (wheel, skill_zip)).encode("ascii"))
    return {"status": "written", "version": version, "sha256sums": str(sums),
            "wheel_sha256": hashes[wheel], "zip_sha256": hashes[skill_zip]}


def compare_releases(directories: Sequence[Path], *, version: str | None = None,
                     pin: Path | None = None) -> dict:
    """Require byte-identical wheel and ZIP in every directory (rebuilds, published assets).

    With ``pin``, that runtime.json must also pin the wheel, as a release tag's does.
    """
    if len(directories) < 2:
        raise ReleaseError("compare needs at least two asset directories")
    first = directories[0].resolve()
    found, reference = _release_assets(first, version)
    for directory in directories[1:]:
        _, hashes = _release_assets(directory.resolve(), found)
        differing = [name for name in reference if hashes[name] != reference[name]]
        if differing:
            raise ReleaseError(f"{directory} differs from {first} in {', '.join(differing)}")
    wheel, skill_zip = _asset_names(found)
    if pin is not None:
        runtime = json.loads(pin.read_text(encoding="utf-8"))
        if runtime.get("version") != found or runtime.get("wheel", {}).get("sha256") != reference[wheel]:
            raise ReleaseError(f"{pin} does not pin the wheel {wheel} found in {first}")
    return {"status": "identical", "version": found,
            "directories": [str(directory) for directory in directories],
            "wheel_sha256": reference[wheel], "zip_sha256": reference[skill_zip],
            "pin_checked": pin is not None}


def _load_sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _default_builder(root: Path, output: Path, *, update_source_manifest: bool) -> dict:
    return _load_sibling("build_distribution").build(
        root, output, update_source_manifest=update_source_manifest)


def _check_bumped_text(root: Path, output: Path, version: str) -> None:
    """The bump's README and CHANGELOG edits are on disk and in the built wheel's README.

    At 0.14.0 those edits were gone seconds after bump wrote them, and the first build
    embedded the old README.
    """
    link = f"releases/tag/v{version}"
    redo = (f"; redo the bump's README and CHANGELOG edits by hand, delete {output}, "
            "and build again")
    for relative in _README_SECTIONS:
        if link not in _read(root / relative):
            raise ReleaseError(f"{relative} does not link {link}{redo}")
    if not re.search(rf"(?m)^## {re.escape(version)} ", _read(root / "CHANGELOG.md")):
        raise ReleaseError(f"CHANGELOG.md has no {version} section{redo}")
    with zipfile.ZipFile(output / _asset_names(version)[0]) as wheel:
        metadata = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
        text = wheel.read(metadata[0]).decode("utf-8") if len(metadata) == 1 else ""
    if link not in text:
        raise ReleaseError(f"the built wheel's README does not link {link}{redo}")


def build_release(root: Path, output: Path | None = None, *,
                  builder: Callable[..., dict] = _default_builder) -> dict:
    """Build into a fresh directory, prove the build reproducible, and write SHA256SUMS."""
    version = current_version(root)
    output = (output or root / "dist" / f"release-{version}").resolve()
    if output.exists():
        raise ReleaseError(f"{output} already exists; remove it or choose another --output")
    builder(root, output, update_source_manifest=True)
    names = _asset_names(version)
    hashes = {name: _sha256(output / name) for name in names}
    with tempfile.TemporaryDirectory(prefix="arp-release-rebuild-") as temporary:
        rebuilt = Path(temporary) / "rebuild"
        builder(root, rebuilt, update_source_manifest=False)
        differing = [name for name in names if _sha256(rebuilt / name) != hashes[name]]
    if differing:
        raise ReleaseError(f"a second build produced different bytes for {', '.join(differing)}")
    runtime = json.loads((root / "skills" / NAME / "runtime.json").read_text(encoding="utf-8"))
    if runtime.get("version") != version or runtime["wheel"]["sha256"] != hashes[names[0]]:
        raise ReleaseError("skills/acquire-research-papers/runtime.json does not pin the built wheel")
    _check_bumped_text(root, output, version)
    (output / "SHA256SUMS").write_bytes(_sums_text(hashes, names).encode("ascii"))
    return {"status": "built", "version": version, "output": str(output),
            "wheel_sha256": hashes[names[0]], "zip_sha256": hashes[names[1]],
            "reproducible": True,
            "next_action": "Smoke-test the ZIP and wheel, commit and tag the release, push main "
                           "and the tag, wait for CI, then run python scripts/release.py publish."}


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _run(command: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(command), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)


def _ok(runner: Runner, command: Sequence[str], what: str) -> str:
    result = runner(command)
    if result.returncode != 0:
        lines = (result.stderr or result.stdout or "").strip().splitlines()
        detail = lines[-1] if lines else f"exit {result.returncode}"
        raise ReleaseError(f"{what} failed: {detail}")
    return result.stdout


def _check_pushed(runner: Runner, tag: str) -> str:
    if _ok(runner, ["git", "status", "--porcelain"], "git status").strip():
        raise ReleaseError("the working tree has uncommitted changes; commit the release first")
    head = _ok(runner, ["git", "rev-parse", "HEAD"], "git rev-parse").strip()
    tagged = runner(["git", "rev-parse", f"{tag}^{{commit}}"])
    if tagged.returncode != 0 or tagged.stdout.strip() != head:
        raise ReleaseError(f"tag {tag} must exist locally and point to HEAD {head[:7]}")
    remote = {}
    for line in _ok(runner, ["git", "ls-remote", "origin", "refs/heads/main",
                             f"refs/tags/{tag}^{{}}"], "git ls-remote").splitlines():
        commit, _, ref = line.partition("\t")
        remote[ref] = commit
    if remote.get("refs/heads/main") != head:
        raise ReleaseError(f"origin main is not HEAD {head[:7]}; push main again and check it")
    if remote.get(f"refs/tags/{tag}^{{}}") != head:
        raise ReleaseError(f"origin has no tag {tag} at HEAD; push the tag")
    return head


def _releases(runner: Runner, repository: str) -> list[dict]:
    return json.loads(_ok(runner, ["gh", "api", f"repos/{repository}/releases?per_page=30"],
                          "listing releases"))


def _with_retries(action: Callable[[], None], what: str, *, attempts: int,
                  sleeper: Callable[[float], None]) -> int:
    for attempt in range(1, attempts + 1):
        try:
            action()
            return attempt
        except ReleaseError:
            if attempt == attempts:
                raise
            sleeper(RETRY_SECONDS)
    raise ReleaseError(f"{what} failed")  # unreachable; keeps type checkers content


def _check_ci(runner: Runner, repository: str, head: str) -> None:
    """Every run of the test workflow for the release commit (main and tag) has passed."""
    runs = json.loads(_ok(runner, [
        "gh", "run", "list", "--repo", repository, "--commit", head, "--workflow", "test",
        "--json", "databaseId,status,conclusion,headBranch"], "listing CI runs"))
    if not runs:
        raise ReleaseError(f"no test workflow run exists for {head[:7]} yet; wait for CI")
    for run in runs:
        if run.get("status") != "completed":
            raise ReleaseError(f"CI is still running for {head[:7]} on {run.get('headBranch')}; "
                               f"wait with gh run watch {run['databaseId']} --exit-status")
        if run.get("conclusion") != "success":
            raise ReleaseError(f"CI run {run['databaseId']} on {run.get('headBranch')} ended "
                               f"{run.get('conclusion')}; fix it or rerun its failed jobs")


def publish(root: Path, *, title: str, notes_file: Path, dist: Path | None = None,
            repository: str = REPOSITORY, runner: Runner = _run, check_ci: bool = True,
            sleeper: Callable[[float], None] = time.sleep) -> dict:
    """Publish the built assets of the current version as GitHub release v<version>."""
    version = current_version(root)
    tag = f"v{version}"
    dist = (dist or root / "dist" / f"release-{version}").resolve()
    if not title.strip():
        raise ReleaseError("--title must not be empty")
    if not notes_file.is_file() or not notes_file.read_text(encoding="utf-8").strip():
        raise ReleaseError(f"release notes file {notes_file} is missing or empty")
    names = (*_asset_names(version), "SHA256SUMS")
    files = [dist / name for name in names]
    missing = [path.name for path in files if not path.is_file()]
    if missing:
        raise ReleaseError(f"missing release assets in {dist}: {', '.join(missing)}; run build")
    expected_sums = "".join(f"{_sha256(path)}  {path.name}\n" for path in files[:2])
    if (dist / "SHA256SUMS").read_bytes().decode("ascii") != expected_sums:
        raise ReleaseError("SHA256SUMS does not match the built assets; run build again")
    runtime = json.loads((root / "skills" / NAME / "runtime.json").read_text(encoding="utf-8"))
    if runtime["wheel"]["sha256"] != _sha256(files[0]):
        raise ReleaseError("runtime.json does not pin the wheel in the release directory")
    head = _check_pushed(runner, tag)
    if check_ci:
        _check_ci(runner, repository, head)

    def drafts() -> list[dict]:
        found = [item for item in _releases(runner, repository) if item.get("tag_name") == tag]
        if any(not item.get("draft") for item in found):
            raise ReleaseError(f"release {tag} is already published")
        if len(found) > 1:
            raise ReleaseError(f"{len(found)} draft releases exist for {tag}; delete the extras")
        return found

    if not drafts():  # a draft left by an interrupted publish is reused
        _ok(runner, ["gh", "release", "create", tag, "--repo", repository, "--verify-tag",
                     "--draft", "--title", title, "--notes-file", str(notes_file)],
            "creating the draft release")
    attempts = {}
    for path in files:
        attempts[path.name] = _with_retries(
            lambda path=path: _ok(runner, ["gh", "release", "upload", tag, str(path), "--repo",
                                           repository, "--clobber"], f"uploading {path.name}"),
            f"uploading {path.name}", attempts=UPLOAD_ATTEMPTS, sleeper=sleeper)
    current = drafts()
    if not current:
        raise ReleaseError(f"the draft release {tag} disappeared before publication")
    uploaded = {asset["name"]: (asset["size"], asset.get("state"))
                for asset in current[0]["assets"]}
    for path in files:
        if uploaded.get(path.name) != (path.stat().st_size, "uploaded"):
            raise ReleaseError(f"uploaded {path.name} is {uploaded.get(path.name)}, expected "
                               f"{path.stat().st_size} bytes")
    if set(uploaded) != set(names):
        raise ReleaseError(f"the draft holds unexpected assets: {sorted(set(uploaded) - set(names))}")
    _ok(runner, ["gh", "release", "edit", tag, "--repo", repository, "--draft=false", "--latest"],
        "publishing the draft")
    with tempfile.TemporaryDirectory(prefix="arp-release-download-") as temporary:
        downloaded = Path(temporary)
        _with_retries(lambda: _ok(runner, ["gh", "release", "download", tag, "--repo", repository,
                                           "--dir", str(downloaded), "--clobber"],
                                  "downloading the published assets"),
                      "downloading the published assets", attempts=3, sleeper=sleeper)
        differing = [path.name for path in files
                     if not (downloaded / path.name).is_file()
                     or _sha256(downloaded / path.name) != _sha256(path)]
    if differing:
        raise ReleaseError(f"published assets differ from the local build: {', '.join(differing)}")
    return {"status": "published", "tag": tag, "commit": head,
            "url": f"https://github.com/{repository}/releases/tag/{tag}",
            "upload_attempts": attempts, "published_assets_match": True,
            "next_action": "Wait for the verify public release workflow, then append the run "
                           "links to the notes with gh release edit --notes-file."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    bump_parser = commands.add_parser("bump", help="rewrite every version string")
    bump_parser.add_argument("version")
    bump_parser.add_argument("--date", help="CHANGELOG date, default today (YYYY-MM-DD)")
    build_parser = commands.add_parser("build", help="build reproducible assets and SHA256SUMS")
    build_parser.add_argument("--output", type=Path)
    smoke_parser = commands.add_parser(
        "smoke", help="bootstrap the built skill in isolated roots and run live checks")
    smoke_parser.add_argument("--public", action="store_true",
                              help="bootstrap from the public release URL, not the built wheel")
    smoke_parser.add_argument("--dist", type=Path)
    publish_parser = commands.add_parser("publish", help="upload and publish the GitHub release")
    publish_parser.add_argument("--title", required=True)
    publish_parser.add_argument("--notes-file", type=Path, required=True)
    publish_parser.add_argument("--dist", type=Path)
    publish_parser.add_argument("--repo", default=REPOSITORY)
    publish_parser.add_argument("--skip-ci-check", action="store_true",
                                help="publish without requiring passed test runs for the commit")
    remote_parser = commands.add_parser(
        "remote", help="install the built skill on a remote host over SSH, with backups")
    remote_parser.add_argument("--host", required=True,
                               help="user@host or an SSH config alias; never stored")
    remote_parser.add_argument("--target", action="append", choices=["kiro", "codex"],
                               help="skills folder to install into (repeatable; default both)")
    remote_parser.add_argument("--dist", type=Path)
    checksums_parser = commands.add_parser(
        "checksums", help="write SHA256SUMS for the wheel and ZIP in a directory")
    checksums_parser.add_argument("directory", type=Path)
    compare_parser = commands.add_parser(
        "compare", help="require byte-identical wheel and ZIP in two or more directories")
    compare_parser.add_argument("directories", type=Path, nargs="+")
    compare_parser.add_argument("--version", help="the version every directory must hold")
    compare_parser.add_argument("--pin", type=Path,
                                help="a runtime.json that must pin the wheel")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "bump":
            result = bump(root, args.version, today=args.date)
        elif args.command == "build":
            if not shutil.which("uv"):
                raise ReleaseError("uv is required to build the wheel")
            result = build_release(root, args.output)
        elif args.command == "smoke":
            result = _load_sibling("release_smoke").smoke(root, dist=args.dist,
                                                          public=args.public)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result["status"] == "passed" else 1
        elif args.command == "remote":
            version = current_version(root)
            dist = (args.dist or root / "dist" / f"release-{version}").resolve()
            result = _load_sibling("release_remote").install_remote(
                dist, version, host=args.host, targets=args.target or ("kiro", "codex"))
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result["status"] == "installed" else 1
        elif args.command == "checksums":
            result = write_checksums(args.directory)
        elif args.command == "compare":
            result = compare_releases(args.directories, version=args.version, pin=args.pin)
        else:
            if not shutil.which("gh"):
                raise ReleaseError("the GitHub CLI (gh) is required to publish")
            result = publish(root, title=args.title, notes_file=args.notes_file.resolve(),
                             dist=args.dist, repository=args.repo,
                             check_ci=not args.skip_ci_check)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "error", "step": args.command, "message": str(exc)},
                         ensure_ascii=False))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
