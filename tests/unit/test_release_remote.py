from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("release_remote", ROOT / "scripts" / "release_remote.py")
release_remote = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = release_remote
spec.loader.exec_module(release_remote)

VERSION = "9.9.9"
STAMP = datetime(2026, 11, 3, 12, 0, 0, tzinfo=UTC)
ARP_STUB = """import json, sys
from pathlib import Path
skill = Path(__file__).resolve().parents[1]
pinned = json.loads((skill / "runtime.json").read_text())["version"]
if sys.argv[1] == "--version":
    print(json.dumps({"version": pinned}))
else:
    print(json.dumps({"status": "ok", "skill": {"runtime_matches_pin": pinned == "9.9.9"}}))
"""


def build_release(dist: Path) -> Path:
    dist.mkdir(parents=True)
    archive = dist / f"acquire-research-papers-skill-{VERSION}.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("acquire-research-papers/runtime.json",
                        f'{{\r\n  "version": "{VERSION}"\r\n}}\r\n')
        bundle.writestr("acquire-research-papers/scripts/arp.py", ARP_STUB)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dist / "SHA256SUMS").write_bytes(f"{'0' * 64}  wheel.whl\n{digest}  {archive.name}\n".encode())
    return archive


class LocalHost:
    """Runs the ssh and scp commands locally, with HOME set to a temporary folder."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.commands: list[list[str]] = []

    def __call__(self, command, stdin=None, cwd=None):
        command = list(command)
        self.commands.append(command)
        environment = {**os.environ, "HOME": str(self.home)}
        if command[0] == "scp":
            *files, destination = [part for part in command[1:] if part not in
                                   ("-q", "-o", "BatchMode=yes", "ConnectTimeout=20")]
            target = self.home / destination.split(":", 1)[1]
            for name in files:
                shutil.copy2(Path(cwd) / name, target / name)
            return subprocess.CompletedProcess(command, 0, b"", b"")
        remote = command[command.index("host.example") + 1:]
        if remote[0] == "mkdir":
            remote = [*remote[:2], str(self.home / remote[2])]
        return subprocess.run(remote, input=stdin, capture_output=True, env=environment,
                              cwd=self.home, check=False)


requires_bash = pytest.mark.skipif(
    os.name == "nt" or not shutil.which("bash") or not shutil.which("python3"),
    reason="the remote scripts run under bash with python3 on Linux or macOS")


@requires_bash
def test_install_backs_up_the_old_skill_and_verifies_the_new_one(tmp_path):
    dist = tmp_path / "dist"
    build_release(dist)
    home = tmp_path / "home"
    old = home / ".kiro" / "skills" / "acquire-research-papers"
    old.mkdir(parents=True)
    (old / "marker").write_text("old skill")
    host = LocalHost(home)

    result = release_remote.install_remote(dist, VERSION, host="host.example", runner=host,
                                           now=lambda: STAMP)

    assert result["status"] == "installed", result
    backup = home / ".arp-skill-backups" / ".kiro-acquire-research-papers-20261103T120000Z"
    assert (backup / "marker").read_text() == "old skill"
    assert [item["backup"] for item in result["skills"]] == [str(backup), None]
    for root in (".kiro", ".codex"):
        runtime = home / root / "skills" / "acquire-research-papers" / "runtime.json"
        assert b"\r" not in runtime.read_bytes()
        assert json.loads(runtime.read_text())["version"] == VERSION
    assert [(item["version"], item["runtime_matches_pin"]) for item in result["skills"]] == [
        (VERSION, True), (VERSION, True)]
    assert not list(home.glob(".arp-skill-staging-*"))


@requires_bash
def test_a_zip_that_does_not_match_sha256sums_installs_nothing(tmp_path):
    dist = tmp_path / "dist"
    archive = build_release(dist)
    archive.write_bytes(archive.read_bytes() + b"tampered")
    home = tmp_path / "home"
    home.mkdir()

    with pytest.raises(release_remote.RemoteError, match="ZIP hash does not match"):
        release_remote.install_remote(dist, VERSION, host="host.example",
                                      runner=LocalHost(home), now=lambda: STAMP)
    assert not (home / ".kiro").exists() and not (home / ".codex").exists()


def test_the_host_is_validated_and_only_named_targets_are_installed(tmp_path):
    dist = tmp_path / "dist"
    build_release(dist)
    calls = []

    def runner(command, stdin=None, cwd=None):
        calls.append(list(command))
        output = b""
        if "--" in command and command[-1] == ".codex/skills":
            output = b"ARP-HASH abc\nARP-INSTALLED .codex/skills\n"
        elif "--" in command:
            output = (b'ARP-VERSION .codex/skills {"version": "9.9.9"}\n'
                      b'ARP-DOCTOR .codex/skills {"status": "ok", "skill": '
                      b'{"runtime_matches_pin": true}}\n')
        return subprocess.CompletedProcess(command, 0, output, b"")

    for host in ("-oProxyCommand=x", "-oX@host", "user@host;rm", "a b"):
        with pytest.raises(release_remote.RemoteError, match="--host"):
            release_remote.install_remote(dist, VERSION, host=host, runner=runner)
    assert calls == []

    result = release_remote.install_remote(dist, VERSION, host="user@203.0.113.7",
                                           targets=("codex",), runner=runner, now=lambda: STAMP)

    assert result["status"] == "installed"
    assert [item["skill"] for item in result["skills"]] == ["~/.codex/skills/acquire-research-papers"]
    scp = next(call for call in calls if call[0] == "scp")
    assert scp[-3:] == [f"acquire-research-papers-skill-{VERSION}.zip", "SHA256SUMS",
                        "user@203.0.113.7:.arp-skill-staging-20261103T120000Z/"]
    assert all("BatchMode=yes" in call for call in calls)


def test_a_skill_that_does_not_report_the_new_version_fails_the_install(tmp_path):
    dist = tmp_path / "dist"
    build_release(dist)

    def runner(command, stdin=None, cwd=None):
        output = b""
        if command[-1] == ".kiro/skills" and ".arp-skill-staging-20261103T120000Z" in command:
            output = b"ARP-INSTALLED .kiro/skills\n"
        elif "--" in command:
            output = b'ARP-VERSION .kiro/skills {"version": "9.9.8"}\nARP-DOCTOR .kiro/skills \n'
        return subprocess.CompletedProcess(command, 0, output, b"")

    result = release_remote.install_remote(dist, VERSION, host="lab", targets=("kiro",),
                                           runner=runner, now=lambda: STAMP)

    assert result["status"] == "failed"
    assert result["failed"] == ["~/.kiro/skills/acquire-research-papers"]
