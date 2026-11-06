"""Fetch an explicit list of DOIs or official URLs in one process (``fetch --input-file``).

One process means one shared IEEE browser and one institution login for the whole list. Each
input gets one ledger row (``fetch-ledger.jsonl`` in the output directory), rewritten after every
paper, so an interrupted list can be inspected and rerun: papers already verified in the same
output are answered from the registry without contacting the publisher again.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from acquire_research_papers.acquisition.corpus import _HostGuard, normalized_state
from acquire_research_papers.acquisition.outcomes import failure_outcome
from acquire_research_papers.acquisition.router import canonical_landing_url, doi_publisher_host
from acquire_research_papers.artifacts import atomic_write_bytes, sha256_file
from acquire_research_papers.delivery import DeliveryResult
from acquire_research_papers.models import normalize_doi

LEDGER_FILE = "fetch-ledger.jsonl"
MAX_INPUTS = 1000
_DOI_HOSTS = frozenset({"doi.org", "dx.doi.org", "www.doi.org"})


def _key(value: str) -> str:
    doi = normalize_doi(value)
    if doi and doi.startswith("10."):
        return f"doi:{doi}"
    return "url:" + value.strip().rstrip("/").casefold()


def read_input_list(path: Path) -> list[str]:
    """One DOI or official URL per line; blank lines and ``#`` comments are skipped."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"--input-file could not be read as UTF-8 text: {path}") from exc
    inputs: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        key = _key(value)
        if key in seen:
            continue  # the same paper twice would only be answered from the registry again
        seen.add(key)
        inputs.append(value)
    if not inputs:
        raise ValueError("--input-file lists no DOI or official URL")
    if len(inputs) > MAX_INPUTS:
        raise ValueError(f"--input-file lists more than {MAX_INPUTS} papers; split the list")
    return inputs


def input_host(value: str) -> str:
    """The publisher host an input will reach, named offline for request spacing."""
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        host = parsed.hostname.casefold().rstrip(".")
        if host in _DOI_HOSTS:
            return doi_publisher_host(parsed.path.lstrip("/")) or host
        try:
            return (urlsplit(canonical_landing_url(candidate)).hostname or host).casefold()
        except ValueError:
            return host
    return doi_publisher_host(normalize_doi(candidate)) or "doi.org"


def _row(index: int, value: str, outcome: Mapping[str, Any]) -> dict[str, Any]:
    state = normalized_state(outcome)
    row: dict[str, Any] = {
        "index": index, "input": value, "state": state,
        "error_code": "" if state == "delivered" else str(outcome.get("error_code", "")),
        "message": " ".join(str(outcome.get("message") or "").split())[:500],
        "pdf": "", "bibtex": "", "provenance": "", "pdf_sha256": "", "bibtex_sha256": "",
    }
    if state == "delivered":
        for kind in ("pdf", "bibtex", "provenance"):
            row[kind] = str(outcome[kind])
        row["pdf_sha256"] = sha256_file(Path(row["pdf"]))
        row["bibtex_sha256"] = sha256_file(Path(row["bibtex"]))
    return row


class FetchListWorkflow:
    def __init__(
        self,
        *,
        fetch: Callable[[str, Path], DeliveryResult],
        min_host_interval_seconds: float = 0.0,
        host_intervals: Mapping[str, float] | None = None,
        transient_failure_limit: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.fetch = fetch
        self.min_host_interval_seconds = min_host_interval_seconds
        self.host_intervals = dict(host_intervals or {})
        self.transient_failure_limit = transient_failure_limit
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._progress = progress or (lambda event: None)

    def run(self, inputs: list[str], output: Path, *, command: str = "arp") -> dict[str, Any]:
        output.mkdir(parents=True, exist_ok=True)
        ledger_path = output / LEDGER_FILE
        guard = _HostGuard(
            min_interval_seconds=self.min_host_interval_seconds,
            transient_failure_limit=self.transient_failure_limit,
            sleeper=self._sleeper, monotonic=self._monotonic, host_intervals=self.host_intervals,
        )
        rows: list[dict[str, Any]] = []
        interrupted = False

        def write_ledger() -> None:
            atomic_write_bytes(ledger_path, "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
            ).encode("utf-8"))

        total = len(inputs)
        for index, value in enumerate(inputs, start=1):
            host = input_host(value)
            paused = guard.paused(host)
            if paused is not None:
                outcome: Mapping[str, Any] = paused
            else:
                try:
                    guard.wait(host)
                    self._progress({"event": "paper_started", "index": index, "total": total,
                                    "input": value})
                    try:
                        result = self.fetch(value, output)
                        outcome = {"status": "delivered", "pdf": result.pdf,
                                   "bibtex": result.bibtex, "provenance": result.provenance}
                    except Exception as exc:  # one shared classification; see outcomes
                        # Keeps the internal pause hint for the guard; rows copy only the
                        # public error code and message.
                        outcome = failure_outcome(exc)
                except KeyboardInterrupt:
                    # Ctrl+C or job stop: keep what is finished and say where the list stopped.
                    interrupted = True
                    break
                guard.record(host, outcome)
            row = _row(index, value, outcome)
            rows.append(row)
            write_ledger()
            self._progress({"event": "paper_finished", "index": index, "total": total,
                            "state": row["state"], "error_code": row["error_code"]})
        not_attempted = inputs[len(rows):]
        write_ledger()
        counts = {state: sum(row["state"] == state for row in rows)
                  for state in ("delivered", "manual_required", "retryable", "contract_error")}
        quoted_output = f'"{output}"' if " " in str(output) else str(output)
        next_actions: list[dict[str, Any]] = [
            {"action": "manual-fetch", "input": row["input"], "reason": row["error_code"],
             "command": f"{command} manual-fetch --input {row['input']} --output {quoted_output}"}
            for row in rows if row["state"] == "manual_required"
        ]
        if counts["retryable"] or not_attempted:
            next_actions.append({
                "action": "rerun",
                "reason": ("interrupted" if not_attempted else "retryable"),
                "message": "rerun the same fetch --input-file command with the same --output "
                           "later; verified papers are not fetched again",
            })
        return {
            "status": "delivered" if counts["delivered"] == total else "partial",
            "total": total, **counts, "not_attempted": len(not_attempted),
            "interrupted": interrupted,
            "fetch_ledger": str(ledger_path),
            "items": [{key: row[key] for key in ("index", "input", "state", "error_code",
                                                  "message", "pdf", "bibtex", "provenance")}
                      for row in rows],
            "next_actions": next_actions,
        }
