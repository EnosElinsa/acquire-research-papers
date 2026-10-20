#!/usr/bin/env python3
"""Run a verified release wheel in a separate uv environment (Python standard library only)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def load_manifest(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (value.get("schema_version") != 1 or value.get("package") != "acquire-research-papers"
            or not re.fullmatch(r"\d+\.\d+\.\d+", str(value.get("version", "")))):
        raise ValueError("unsupported release manifest")
    wheel = value.get("wheel") or {}
    url = urlsplit(wheel.get("url", ""))
    if (url.scheme != "https" or url.hostname != "github.com" or url.username or url.password
            or url.query or url.fragment or not url.path.startswith(
                "/EnosElinsa/acquire-research-papers/releases/download/v" + value["version"] + "/")):
        raise ValueError("release wheel must use the fixed project HTTPS release URL")
    expected = "acquire_research_papers-" + value["version"] + "-py3-none-any.whl"
    if Path(url.path).name != expected or not re.fullmatch(r"[0-9a-f]{64}", str(wheel.get("sha256", ""))):
        raise ValueError("release wheel name or SHA-256 is invalid")
    return value


def runtime_root() -> Path:
    if os.environ.get("ARP_RUNTIME_ROOT"):
        return Path(os.environ["ARP_RUNTIME_ROOT"]).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    legacy = base / "Codex" / "runtimes" / "acquire-research-papers"
    # Reuse an existing cache in place; never copy or silently discard it.
    return legacy if legacy.is_dir() else base / "acquire-research-papers" / "runtimes"


def prepare_runtime(manifest_path: Path) -> Path:
    manifest = load_manifest(manifest_path)
    release = manifest["wheel"]
    expected = release["sha256"]
    root = runtime_root()
    local = os.environ.get("ARP_LOCAL_WHEEL")
    if local:
        wheel = Path(local).expanduser().resolve()
        if not wheel.is_file() or sha256(wheel) != expected:
            raise ValueError("local wheel SHA-256 does not match the release manifest")
    else:
        wheel = root / "wheels" / Path(urlsplit(release["url"]).path).name
        if wheel.exists() and sha256(wheel) != expected:
            raise ValueError("cached release wheel SHA-256 mismatch; remove the corrupt cached wheel")
        if not wheel.exists():
            wheel.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                request = urllib.request.Request(release["url"], headers={"User-Agent": "arp-skill-launcher"})
                with urllib.request.urlopen(request, timeout=30) as incoming:
                    with tempfile.NamedTemporaryFile(dir=wheel.parent, delete=False) as outgoing:
                        temporary = Path(outgoing.name)
                        total = 0
                        for block in iter(lambda: incoming.read(1024 * 1024), b""):
                            total += len(block)
                            if total > 64 * 1024 * 1024:
                                raise ValueError("release wheel exceeds the 64 MiB limit")
                            outgoing.write(block)
                if sha256(temporary) != expected:
                    raise ValueError("downloaded release wheel SHA-256 mismatch")
                temporary.replace(wheel)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
    environment = root / (manifest["version"] + "-" + expected[:16])
    interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    marker = environment / "installed.json"
    if marker.is_file() and interpreter.is_file():
        installed = json.loads(marker.read_text(encoding="utf-8"))
        if installed == {"version": manifest["version"], "sha256": expected}:
            return interpreter
    uv = os.environ.get("ARP_UV") or shutil.which("uv")
    if not uv:
        raise ValueError("uv is required; install it from https://docs.astral.sh/uv/")
    root.mkdir(parents=True, exist_ok=True)
    # Neither command discovers a developer project or installs an editable checkout.
    subprocess.run([uv, "--no-config", "venv", "--allow-existing", "--python", sys.executable,
                    str(environment)], check=True)
    subprocess.run([uv, "--no-config", "pip", "install", "--python", str(interpreter),
                    "--only-binary", ":all:", str(wheel)], check=True)
    temporary_marker = marker.with_suffix(".tmp")
    temporary_marker.write_text(json.dumps({"version": manifest["version"], "sha256": expected}) + "\n",
                                encoding="utf-8")
    temporary_marker.replace(marker)
    return interpreter


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        print("Python 3.11 or newer is required", file=sys.stderr)
        return 2
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        manifest = Path(__file__).resolve().parents[1] / "runtime.json"
        interpreter = prepare_runtime(manifest)
        return subprocess.run([str(interpreter), "-m", "acquire_research_papers", *arguments],
                              check=False).returncode
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        # Remote URLs can contain signed query values; diagnostics expose only the error class.
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(json.dumps({"status": "launcher_error", "error": detail}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
