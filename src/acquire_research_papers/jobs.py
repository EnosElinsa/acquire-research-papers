"""Run one long arp command in the background and follow it through files.

Agent hosts often stop a shell command after a few minutes, while a manual-download session,
an institution login, or a large discovery can take much longer. ``arp --background <job-dir>
<command> ...`` starts the command as its own process and returns at once. ``arp job status``
reports progress and, once the command ends, the JSON result it would have printed.
``arp job stop`` asks the command to end at its next safe point, exactly as Ctrl+C would.

Files in the job directory: ``job.json`` (command and process ID), ``output.jsonl`` (the
command's stdout), ``progress.log`` (its stderr), ``exit.json`` (written when it ends), and
``stop-requested``.
"""
from __future__ import annotations

import _thread
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from acquire_research_papers.artifacts import atomic_write_bytes

# Commands that can run long and need no terminal input.
BACKGROUND_COMMANDS = frozenset({"fetch", "manual-fetch", "discover", "acquire"})
JOB_FILE = "job.json"
OUTPUT_FILE = "output.jsonl"
PROGRESS_FILE = "progress.log"
EXIT_FILE = "exit.json"
STOP_FILE = "stop-requested"
# Under the data root: one line per started job, read by job list.
INDEX_FILE = "background-jobs.jsonl"
PROGRESS_LINES = 20
STOP_POLL_SECONDS = 0.5


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write_bytes(
        path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def strip_background_option(argv: Sequence[str]) -> list[str]:
    """The command line without its first ``--background`` option."""
    remaining = list(argv)
    for index, value in enumerate(remaining):
        if value == "--background":
            del remaining[index:index + 2]
            return remaining
        if value.startswith("--background="):
            del remaining[index]
            return remaining
    return remaining


def _spawn(popen: Callable[..., Any], command: list[str], stdout, stderr) -> Any:
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL, "stdout": stdout, "stderr": stderr, "close_fds": True,
        # A detached process has no console; keep its files UTF-8 whatever the locale.
        "env": {**os.environ, "PYTHONIOENCODING": "utf-8"},
    }
    if os.name != "nt":
        return popen(command, start_new_session=True, **options)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    try:
        # Leave the host's job object so closing the host's shell does not end the job.
        return popen(command, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB,
                     **options)
    except OSError:
        # The host's job object forbids breakaway; the job then lives as long as the host lets it.
        return popen(command, creationflags=flags, **options)


def start(
    job_dir: Path,
    command: str,
    argv: Sequence[str],
    *,
    index: Path | None = None,
    popen: Callable[..., Any] = subprocess.Popen,
    executable: str = sys.executable,
) -> dict[str, Any]:
    if command not in BACKGROUND_COMMANDS:
        raise ValueError(
            "--background runs only " + ", ".join(sorted(BACKGROUND_COMMANDS)) + " commands")
    root = job_dir.resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError("--background needs a new or empty job directory")
    root.mkdir(parents=True, exist_ok=True)
    child = [executable, "-m", "acquire_research_papers", "job", "run", "--job", str(root),
             "--", *argv]
    with (root / OUTPUT_FILE).open("wb") as stdout, (root / PROGRESS_FILE).open("wb") as stderr:
        process = _spawn(popen, child, stdout, stderr)
    started_at = _now()
    _write_json(root / JOB_FILE, {"schema_version": 1, "command": list(argv),
                                  "pid": process.pid, "started_at": started_at})
    if index is not None:
        # Only the job's location is indexed; job list reads everything else from the job.
        index.parent.mkdir(parents=True, exist_ok=True)
        with index.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"job": str(root), "started_at": started_at}) + "\n")
    return {
        "status": "started", "job": str(root), "pid": process.pid, "command": command,
        "next_actions": [{"action": "job status",
                          "command": f"arp job status --job {root} --wait 60"}],
    }


def run(job_dir: Path, argv: Sequence[str], *, runner: Callable[[list[str]], int]) -> int:
    """Body of the background process: run the command and record how it ended."""
    root = job_dir.resolve()
    finished = threading.Event()

    def watch_stop() -> None:
        while not finished.wait(STOP_POLL_SECONDS):
            if (root / STOP_FILE).exists():
                # The command sees a KeyboardInterrupt, as if the user pressed Ctrl+C.
                _thread.interrupt_main()
                return

    threading.Thread(target=watch_stop, daemon=True).start()
    code = 1
    try:
        code = runner(list(argv))
    except KeyboardInterrupt:
        code = 130
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    finally:
        finished.set()
        _write_json(root / EXIT_FILE, {"exit_code": code, "finished_at": _now(),
                                       "stop_requested": (root / STOP_FILE).exists()})
    return code


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill(pid: int) -> None:
    if os.name == "nt":
        os.kill(pid, signal.SIGTERM)  # TerminateProcess
    else:
        os.killpg(pid, signal.SIGTERM)  # the job's own session, including browser helpers


def _job(root: Path, *, attempts: int = 15, sleeper: Callable[[float], None] = time.sleep
         ) -> dict[str, Any]:
    path = root / JOB_FILE
    failure = "missing"
    job: dict[str, Any] | None = None
    for attempt in range(attempts):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            job = value if isinstance(value, dict) else None
            failure = "" if job is not None else "not an object"
            break
        except FileNotFoundError:
            failure = "missing"
            break
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            # A just-written file can be held briefly by another process (for example a virus
            # scan) on Windows; wait for it instead of reporting a broken job.
            failure = type(exc).__name__
            if attempt + 1 < attempts:
                sleeper(0.2)
    if job is None or job.get("schema_version") != 1 or not isinstance(job.get("pid"), int):
        reason = f"; job.json {failure}" if failure else ""
        raise ValueError(f"not a background job directory: {root}{reason}")
    return job


def _last_result(root: Path) -> dict[str, Any] | None:
    try:
        lines = (root / OUTPUT_FILE).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _progress(root: Path) -> list[str]:
    try:
        lines = (root / PROGRESS_FILE).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [line for line in lines if line.strip()][-PROGRESS_LINES:]


def _report(root: Path, job: dict[str, Any], alive: Callable[[int], bool]) -> dict[str, Any]:
    base = {"job": str(root), "command": (job.get("command") or [""])[0], "pid": job["pid"],
            "started_at": job.get("started_at"), "progress": _progress(root)}
    ended = _read_json(root / EXIT_FILE)
    if ended is None and alive(job["pid"]):
        return {**base, "status": "running", "next_actions": [
            {"action": "job status", "command": f"arp job status --job {root} --wait 60"}]}
    ended = ended or _read_json(root / EXIT_FILE)
    stop_requested = (root / STOP_FILE).exists()
    if ended is None:
        # The process is gone without recording an end: killed, or the machine restarted.
        return {**base, "status": "stopped" if stop_requested else "crashed",
                "result": _last_result(root)}
    return {**base, "status": "stopped" if ended.get("stop_requested") else "finished",
            "exit_code": ended.get("exit_code"), "finished_at": ended.get("finished_at"),
            "result": _last_result(root)}


def status(
    job_dir: Path,
    *,
    wait_seconds: float = 0.0,
    alive: Callable[[int], bool] = pid_alive,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Report a job; with ``wait_seconds``, wait up to that long for it to end."""
    root = job_dir.resolve()
    job = _job(root)
    deadline = monotonic() + max(0.0, wait_seconds)
    while True:
        report = _report(root, job, alive)
        remaining = deadline - monotonic()
        if report["status"] != "running" or remaining <= 0:
            return report
        sleeper(min(1.0, remaining))


def list_jobs(index: Path, *, alive: Callable[[int], bool] = pid_alive) -> dict[str, Any]:
    """Every indexed job that still has its directory, newest first."""
    try:
        lines = index.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    seen: set[str] = set()
    jobs: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            location = str(json.loads(line)["job"])
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        if location in seen:
            continue
        seen.add(location)
        root = Path(location)
        try:
            report = _report(root, _job(root), alive)
        except ValueError:
            continue  # removed or not a job directory any more
        result = report.get("result") or {}
        jobs.append({"job": report["job"], "command": report["command"],
                     "status": report["status"], "started_at": report["started_at"],
                     "finished_at": report.get("finished_at"), "exit_code": report.get("exit_code"),
                     "result_status": result.get("status") if isinstance(result, dict) else None})
    return {"status": "complete", "jobs": jobs,
            "running": sum(job["status"] == "running" for job in jobs)}


def stop(
    job_dir: Path,
    *,
    force: bool = False,
    alive: Callable[[int], bool] = pid_alive,
    kill: Callable[[int], None] = _kill,
) -> dict[str, Any]:
    root = job_dir.resolve()
    job = _job(root)
    if (root / EXIT_FILE).exists() or not alive(job["pid"]):
        return status(root, alive=alive)
    (root / STOP_FILE).write_text(_now(), encoding="utf-8")
    if force:
        kill(job["pid"])
    return {"status": "killed" if force else "stop_requested", "job": str(root),
            "next_actions": [{"action": "job status",
                              "command": f"arp job status --job {root} --wait 30"}]}
