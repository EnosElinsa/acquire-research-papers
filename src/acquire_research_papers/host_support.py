"""Host installation hints and opt-in diagnostics, independent of host SDKs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import Request, urlopen

from jsonschema.validators import validator_for

from acquire_research_papers import __version__
from acquire_research_papers.file_credentials import API_KEYS, CredentialManager
from acquire_research_papers.paths import AppPaths
from acquire_research_papers.schema_resources import SCHEMA_ROOT

HOSTS = {
    "codex": (".agents", "codex"),
    "claude-code": (".claude", "claude"),
    "kiro-ide": (".kiro", None),
    "kiro-cli": (".kiro", "kiro-cli"),
}


def skill_directory(host: str, *, home: Path | None = None,
                    project_root: Path | None = None) -> Path:
    if host not in HOSTS:
        raise ValueError("unsupported host")
    return (project_root or home or Path.home()) / HOSTS[host][0] / "skills" / (
        "acquire-research-papers")


def register(subparsers) -> None:
    parser = subparsers.add_parser("doctor", help="inspect local runtime and a selected host")
    parser.add_argument("--host", choices=tuple(HOSTS), required=True)
    parser.add_argument("--skill-directory", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--check-host-version", action="store_true",
                        help="run the selected host executable with --version")
    parser.add_argument("--remote-check", action="store_true",
                        help="probe public Crossref reachability without credentials")


def _skill(path: Path) -> dict:
    missing = [name for name in ("SKILL.md", "scripts/arp.py", "runtime.json")
               if not (path / name).is_file()]
    if missing:
        return {"status": "missing", "path": str(path), "missing": missing}
    try:
        manifest = json.loads((path / "runtime.json").read_text(encoding="utf-8"))
        digest = manifest["wheel"]["sha256"]
        if (manifest["schema_version"] != 1 or
                manifest["package"] != "acquire-research-papers" or
                not isinstance(digest, str) or len(digest) != 64 or
                any(character not in "0123456789abcdefABCDEF" for character in digest)):
            raise ValueError
        pinned = manifest["version"]
        if not isinstance(pinned, str):
            raise ValueError
    except (KeyError, TypeError, ValueError, OSError, UnicodeError):
        return {"status": "invalid_manifest", "path": str(path)}
    return {"status": "present", "path": str(path), "pinned_version": pinned,
            "runtime_matches_pin": pinned == __version__}


def _schemas() -> dict:
    invalid = []
    files = sorted(SCHEMA_ROOT.glob("*.schema.json"))
    for path in files:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            validator_for(value).check_schema(value)
        except Exception:
            # Schema contents and validation exceptions may contain input data.
            invalid.append(path.name)
    return {"status": "valid" if files and not invalid else "invalid",
            "root": str(SCHEMA_ROOT), "checked": len(files), "invalid_files": invalid}


def _configuration(paths: AppPaths, *, env_file: Path | None = None) -> dict:
    try:
        manager = CredentialManager(paths, env_file=env_file)
        if manager.backend == "dpapi":
            # Local inventory must not silently invoke the Windows bridge.
            return {"status": "legacy_unchecked", "backend": "dpapi",
                    "root": str(paths.config), "api_keys": {key: None for key in API_KEYS}}
        return {"status": "checked", "backend": manager.backend, "root": str(paths.config),
                "env_file": str(manager.env_file), "api_keys": {
                    key: value for key, value in manager.status().items() if key in API_KEYS}}
    except (ValueError, OSError):
        return {"status": "invalid", "root": str(paths.config),
                "message": "Local configuration could not be read; use config status locally."}


def _host_executable(host: str, *, check_version: bool) -> dict:
    name = HOSTS[host][1]
    path = shutil.which(name) if name else None
    result = {"status": "present" if path else "not_detected", "name": name,
              "path": path, "version_status": "not_checked"}
    if check_version and path:
        try:
            process = subprocess.run([path, "--version"], capture_output=True, text=True,
                timeout=10, check=False, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            output = process.stdout.strip().splitlines()
            if process.returncode == 0 and output:
                result.update(version_status="checked", version="".join(
                    character for character in output[0][:160] if character.isprintable()))
            else:
                result["version_status"] = "failed"
        except (OSError, subprocess.SubprocessError):
            result["version_status"] = "failed"
    return result


def _remote(enabled: bool) -> dict:
    if not enabled:
        return {"status": "unknown", "checked": False}
    try:
        request = Request("https://api.crossref.org/works?rows=0",
                          headers={"User-Agent": "acquire-research-papers-doctor"})
        with urlopen(request, timeout=10) as response:
            status = response.status
        return {"status": "reachable" if 200 <= status < 300 else "unavailable",
                "checked": True, "provider": "crossref", "http_status": status}
    except Exception:
        return {"status": "unavailable", "checked": True, "provider": "crossref"}


def _platform_information() -> dict:
    # platform.uname() can run cmd.exe on Python 3.11/Windows. Doctor's
    # default inventory must stay in-process even on a cold platform cache.
    if os.name == "nt":
        version = sys.getwindowsversion()
        return {"system": "Windows",
                "release": f"{version.major}.{version.minor}.{version.build}"}
    version = os.uname()
    return {"system": version.sysname, "release": version.release}


def dispatch(args: argparse.Namespace) -> dict:
    path = (args.skill_directory or skill_directory(
        args.host, project_root=args.project_root)).expanduser().resolve()
    paths = AppPaths.default()
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(), "host": args.host,
        "platform": _platform_information(),
        "python": {"version": platform.python_version(), "supported": sys.version_info >= (3, 11)},
        "runtime": {"version": __version__, "status": "imported"},
        "skill": _skill(path), "schemas": _schemas(),
        "host_executable": _host_executable(args.host, check_version=args.check_host_version),
        "dependencies": {name: {"available": bool(shutil.which(name))}
                         for name in ("uv", "node", "powershell", "pwsh")},
        "configuration": _configuration(paths, env_file=getattr(args, "env_file", None)),
        "remote": _remote(args.remote_check),
        "host_load": {"status": "unverified",
                      "message": "Confirm this skill appears and can be invoked in the selected host."},
        "institution_access": {"status": "unverified",
                               "message": "Use config ieee doctor with a representative reference."},
    }
    actions = []
    if report["skill"]["status"] != "present":
        actions.append("Install the exported thin skill at the reported path or pass --skill-directory.")
    elif not report["skill"]["runtime_matches_pin"]:
        actions.append("Run the installed skill launcher to use its pinned runtime version.")
    if report["schemas"]["status"] != "valid":
        actions.append("Reinstall the runtime with its bundled public schemas.")
    if report["configuration"]["status"] == "invalid":
        actions.append("Inspect configuration locally; do not paste its contents into chat.")
    report["status"] = "attention_required" if actions else "local_checks_complete"
    report["next_actions"] = actions
    return report
