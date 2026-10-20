"""Small, host-independent execution records; never an application workflow engine."""
from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from acquire_research_papers.artifacts import (
    atomic_write_bytes, sanitize_artifact_value, sha256_bytes, sha256_file,
)
from acquire_research_papers.contracts import validate_contract


class RunLocked(ValueError):
    """Another process owns this run directory."""


def content_hash(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode("utf-8"))


def artifact_reference(path: Path, *, step: str = "", kind: str = "file") -> dict:
    resolved = path.resolve(strict=True)
    result = {"type": kind, "path": str(resolved), "sha256": sha256_file(resolved), "step": step}
    validate_contract(result, "artifact-reference.schema.json")
    return result


def _unchanged(references: Sequence[Mapping]) -> bool:
    try:
        return all(sha256_file(Path(item["path"])) == item["sha256"] for item in references)
    except (OSError, KeyError):
        return False


class RunContext:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / "run-context.json"

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        # The OS releases this lock on process death. The lock file is deliberately
        # persistent: unlinking it would let another process lock a different inode.
        with (self.root / ".arp-run.lock").open("a+b") as handle:
            handle.seek(0)
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RunLocked("run is in use; retry after the active command finishes") from exc
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load(self) -> dict:
        if not self.path.exists():
            return {"schema_version": 1, "steps": {}}
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if state["schema_version"] != 1 or not isinstance(state["steps"], dict):
                raise ValueError
            validate_contract(state, "run-context.schema.json")
            return state
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("invalid run-context.json; preserve the file for diagnosis") from exc

    def _save(self, state: dict) -> None:
        validate_contract(state, "run-context.schema.json")
        atomic_write_bytes(self.path, (json.dumps(sanitize_artifact_value(state),
                            ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))

    def status(self) -> dict:
        state = self._load()
        actions = []
        for name, step in state["steps"].items():
            if step["status"] == "complete":
                input_changed = not _unchanged(step.get("inputs", []))
                output_changed = not _unchanged(step.get("artifacts", []))
                if input_changed or output_changed:
                    step["status"] = "stale"
                    step["next_actions"] = [{"action": "rerun", "step": name,
                                             "reason": reason} for reason, changed in (
                        ("input_changed", input_changed), ("output_changed", output_changed)
                    ) if changed]
            if step["status"] == "running":
                step["next_actions"] = [{"action": "resume", "step": name,
                                         "reason": "running_or_interrupted"}]
            actions.extend(step.get("next_actions", []))
        return {**state, "run": str(self.root), "next_actions": actions}

    def execute(self, name: str, *, inputs: Sequence[Path], parameters: Mapping,
                operation: Callable[[], dict]) -> dict:
        with self.lock():
            state = self._load()
            references = [artifact_reference(path) for path in inputs]
            fingerprint = content_hash({"inputs": references, "parameters": parameters})
            previous = state["steps"].get(name, {})
            if (previous.get("status") == "complete"
                    and previous.get("input_sha256") == fingerprint
                    and _unchanged(previous.get("artifacts", []))):
                return {**previous["result"], "reused": True}
            step = {"status": "running", "input_sha256": fingerprint, "inputs": references,
                    "artifacts": [], "next_actions": []}
            state["steps"][name] = step
            self._save(state)
            try:
                result = operation()
                # Caller returns public, structured results only. Raw exceptions and
                # configuration snapshots are never persisted.
                artifacts = [artifact_reference(Path(path), step=name)
                             for path in result.get("outputs", [])]
                if result.get("status", "complete") == "complete" and not _unchanged(references):
                    result = {**result, "status": "stale", "next_actions": [
                        {"action": "rerun", "step": name, "reason": "input_changed"}]}
                step.update(status=result.get("status", "complete"), result=result,
                            artifacts=artifacts, items=result.get("items", {}),
                            next_actions=result.get("next_actions", []))
                self._save(state)
                return result
            except BaseException:
                step.update(status="failed", next_actions=[{"action": "resume", "step": name}])
                self._save(state)
                raise
