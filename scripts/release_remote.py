"""Install a built release on a remote Linux or macOS host over SSH, run through
``python scripts/release.py remote --host user@host``.

The host is a runtime argument and is never stored. Key-based SSH must already work
(``ssh -o BatchMode=yes``; no password prompts). The skill ZIP and ``SHA256SUMS`` are copied
into a fresh staging folder in the remote home, the ZIP hash is checked there, each existing
skill folder is moved to ``~/.arp-skill-backups/<.kiro|.codex>-acquire-research-papers-<UTC
stamp>``, and the new skill is copied in. Each installed skill then reports its version and
``doctor`` result. The first ``--version`` downloads the pinned wheel from the public release
URL, so run this after ``publish``.
"""
from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NAME = "acquire-research-papers"
# Skills folder (relative to the remote home) and the doctor host name for each target.
TARGETS = {"kiro": (".kiro/skills", "kiro-cli"), "codex": (".codex/skills", "codex")}
# Neither part may start with "-", which ssh would read as an option.
_HOST = re.compile(r"(?:[A-Za-z0-9_][A-Za-z0-9._-]*@)?[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=20")

INSTALL_SCRIPT = r"""set -euo pipefail
stamp="$1"; version="$2"; staging="$HOME/$3"; shift 3
name="acquire-research-papers-skill-$version.zip"
cd "$staging"
expected=$(awk -v n="$name" '$2 == n {print $1}' SHA256SUMS)
if command -v sha256sum >/dev/null; then actual=$(sha256sum "$name" | cut -d' ' -f1)
else actual=$(shasum -a 256 "$name" | cut -d' ' -f1); fi
if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
  echo "ARP-ERROR the ZIP hash does not match SHA256SUMS"; exit 1
fi
echo "ARP-HASH $actual"
python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' \
  "$name" extracted
source="$staging/extracted/acquire-research-papers"
if ! grep -q "\"version\": \"$version\"" "$source/runtime.json"; then
  echo "ARP-ERROR runtime.json in the ZIP does not pin $version"; exit 1
fi
mkdir -p "$HOME/.arp-skill-backups"
for root in "$@"; do
  mkdir -p "$HOME/$root"
  target="$HOME/$root/acquire-research-papers"
  if [ -e "$target" ]; then
    backup="$HOME/.arp-skill-backups/$(dirname "$root" | tr / -)-acquire-research-papers-$stamp"
    mv "$target" "$backup"
    echo "ARP-BACKUP $root $backup"
  fi
  cp -R "$source" "$target"
  # A ZIP built on Windows can carry CRLF line ends; the launcher reads runtime.json as JSON.
  tr -d '\r' < "$target/runtime.json" > "$target/runtime.json.lf"
  mv "$target/runtime.json.lf" "$target/runtime.json"
  echo "ARP-INSTALLED $root"
done
cd "$HOME"
rm -rf "$staging"
"""

VERIFY_SCRIPT = r"""set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
for pair in "$@"; do
  root="${pair%%=*}"; kind="${pair#*=}"
  skill="$HOME/$root/acquire-research-papers"
  version=$(python3 "$skill/scripts/arp.py" --version </dev/null 2>/dev/null | tail -n 1)
  echo "ARP-VERSION $root $version"
  doctor=$(python3 "$skill/scripts/arp.py" doctor --host "$kind" --skill-directory "$skill" \
    </dev/null 2>/dev/null | tail -n 1)
  echo "ARP-DOCTOR $root $doctor"
done
"""

Runner = Callable[[Sequence[str], bytes | None, Path | None], subprocess.CompletedProcess]


class RemoteError(RuntimeError):
    """A remote install step failed; nothing after it ran."""


def _run(command: Sequence[str], stdin: bytes | None = None,
         cwd: Path | None = None) -> subprocess.CompletedProcess:
    # Bytes, not text: on Windows a text-mode pipe would send the bash script with CRLF.
    return subprocess.run(list(command), input=stdin, capture_output=True, cwd=cwd,
                          check=False, timeout=1800)


def _ok(runner: Runner, command: Sequence[str], what: str, stdin: bytes | None = None,
        cwd: Path | None = None) -> str:
    result = runner(command, stdin, cwd)
    output = (result.stdout or b"").decode("utf-8", "replace")
    if result.returncode != 0:
        errors = [line for line in output.splitlines() if line.startswith("ARP-ERROR ")]
        lines = (result.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        detail = (errors[-1][len("ARP-ERROR "):] if errors
                  else lines[-1] if lines else f"exit {result.returncode}")
        raise RemoteError(f"{what} failed: {detail}")
    return output


def _tagged(output: str, tag: str) -> list[tuple[str, str]]:
    """``(first word, rest)`` of each ``ARP-<tag>`` line."""
    found = []
    for line in output.splitlines():
        if line.startswith(f"ARP-{tag} "):
            first, _, rest = line[len(tag) + 5:].partition(" ")
            found.append((first, rest.strip()))
    return found


def _json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def install_remote(dist: Path, version: str, *, host: str,
                   targets: Sequence[str] = tuple(TARGETS), runner: Runner = _run,
                   now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> dict[str, Any]:
    """Copy, check, back up, install, and verify release ``version`` on ``host``."""
    if not _HOST.fullmatch(host):
        raise RemoteError("--host must look like user@host or an SSH config alias")
    unknown = sorted(set(targets) - set(TARGETS))
    if unknown or not targets:
        raise RemoteError(f"--target must name {' or '.join(TARGETS)}, got {unknown or 'none'}")
    archive = f"{NAME}-skill-{version}.zip"
    if not (dist / archive).is_file() or not (dist / "SHA256SUMS").is_file():
        raise RemoteError(f"{archive} or SHA256SUMS is missing in {dist}; run build")
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    staging = f".arp-skill-staging-{stamp}"
    roots = [TARGETS[target][0] for target in dict.fromkeys(targets)]
    _ok(runner, ["ssh", *_SSH_OPTIONS, host, "mkdir", "-p", staging], "creating the staging folder")
    # Names relative to the release folder: scp can read C:\... as a host named C.
    _ok(runner, ["scp", "-q", *_SSH_OPTIONS, archive, "SHA256SUMS", f"{host}:{staging}/"],
        "copying the ZIP and SHA256SUMS", cwd=dist)
    installed = _ok(runner, ["ssh", *_SSH_OPTIONS, host, "bash", "-s", "--", stamp, version,
                             staging, *roots], "installing", INSTALL_SCRIPT.encode("utf-8"))
    backups = dict(_tagged(installed, "BACKUP"))
    if [root for root, _ in _tagged(installed, "INSTALLED")] != roots:
        raise RemoteError("the remote install did not report every target")
    pairs = [f"{TARGETS[target][0]}={TARGETS[target][1]}" for target in dict.fromkeys(targets)]
    verified = _ok(runner, ["ssh", *_SSH_OPTIONS, host, "bash", "-s", "--", *pairs],
                   "verifying", VERIFY_SCRIPT.encode("utf-8"))
    versions = {root: _json(text).get("version") for root, text in _tagged(verified, "VERSION")}
    doctors = {root: _json(text) for root, text in _tagged(verified, "DOCTOR")}
    skills = []
    for root in roots:
        doctor = doctors.get(root, {})
        pinned = (doctor.get("skill") or {}).get("runtime_matches_pin")
        skills.append({"skill": f"~/{root}/{NAME}", "version": versions.get(root),
                       "runtime_matches_pin": pinned, "doctor": doctor.get("status"),
                       "backup": backups.get(root),
                       "passed": versions.get(root) == version and pinned is True})
    failed = [item["skill"] for item in skills if not item["passed"]]
    return {"status": "failed" if failed else "installed", "version": version,
            "zip_sha256": (_tagged(installed, "HASH") or [("", "")])[0][0], "skills": skills,
            "failed": failed,
            "next_action": ("Restore a skill from its backup folder with mv if it must go back."
                            if failed else "Run a fetch on the remote host if this release "
                            "changed an adapter.")}
