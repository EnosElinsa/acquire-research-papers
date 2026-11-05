"""Weekly live check that the built-in venue presets, official indexes, and open-access
fetches still work.

  uv run python scripts/check_sources.py [--only presets|indexes|fetches] [--sample 3]

Presets: every ISSN must still name the preset's journal in Crossref and have records in the
last full year; every Crossref collection DOI must still have records; every OpenAlex source
must still resolve to itself and list works two years back (recent editions can lag). OpenAlex
checks need ``OPENALEX_API_KEY`` and are reported as skipped without it.

Indexes: each official proceedings index is read for one known year. A listing must still
yield close to its known paper count, and a few sample paper pages (``--sample``) must still
parse with an abstract, so a changed page layout shows up here before it reaches a user.

Fetches: the release smoke's open-access papers are fetched with ``arp fetch`` in throwaway
data and config roots, without API keys, and must be delivered with PDF and official BibTeX.

A check that fails with a temporary fault (connection error, HTTP 5xx, or HTTP 429) runs once
more after 30 seconds and is marked "after a retry". If it fails that way again, it is
reported as ``upstream_error`` instead of ``failed``: the remote server is at fault, so there
is nothing to fix here, but the report lists it. Error text keeps only the host of each URL,
since a query can carry an API key.

Prints one JSON object; exits 1 when any check fails.
"""
from __future__ import annotations

import argparse
import html
import importlib.util
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from acquire_research_papers.acquisition.adapters.ijcai import IJCAI_HOSTS  # noqa: E402
from acquire_research_papers.discovery.contracts import DiscoveryRequest  # noqa: E402
from acquire_research_papers.discovery.official.acl import AclAnthologyDiscoveryProvider  # noqa: E402
from acquire_research_papers.discovery.official.archives import (  # noqa: E402
    CvfIndexProvider,
    IclrIndexProvider,
    NeuripsIndexProvider,
    PmlrIndexProvider,
    UsenixIndexProvider,
)
from acquire_research_papers.discovery.official.ijcai import IjcaiDiscoveryProvider  # noqa: E402
from acquire_research_papers.discovery.openalex import OpenAlexClient  # noqa: E402
from acquire_research_papers.discovery.venue_presets import PRESETS, VenuePreset  # noqa: E402
from acquire_research_papers.http import (  # noqa: E402
    HttpStatusError,
    NetworkTransient,
    RateLimited,
    SafeHttpClient,
)

CROSSREF = "https://api.crossref.org"
CROSSREF_PAUSE_SECONDS = 1.0  # Crossref's public pool answers bursts with HTTP 429
RETRY = {"retries": 3, "backoff_seconds": 2.0}
# Outcomes that say "try again later"; such a check runs once more before it counts.
TRANSIENT = frozenset({"network_transient", "rate_limited"})
RETRY_PAUSE_SECONDS = 30.0
Fetch = Callable[[str, Path], tuple[int, dict[str, Any]]]


@dataclass(frozen=True)
class IndexCase:
    """One official index slice and the paper count it listed when the check was written."""

    venue: str
    year: int
    minimum: int
    make: Callable[[], Any]
    exact: bool = False


INDEX_CASES = (
    IndexCase("ACL", 2023, 850, lambda: AclAnthologyDiscoveryProvider(
        client=SafeHttpClient(allowed_hosts={"aclanthology.org"}, timeout=120.0, **RETRY))),
    IndexCase("IJCAI", 2023, 600, lambda: IjcaiDiscoveryProvider(
        client=SafeHttpClient(allowed_hosts=set(IJCAI_HOSTS), timeout=120.0, **RETRY))),
    IndexCase("NeurIPS", 2023, 3000, lambda: NeuripsIndexProvider(
        SafeHttpClient(allowed_hosts={"proceedings.neurips.cc"}, timeout=120.0, **RETRY))),
    IndexCase("ICML", 2023, 1828, lambda: PmlrIndexProvider(
        SafeHttpClient(allowed_hosts={"proceedings.mlr.press"}, timeout=120.0, **RETRY)),
        exact=True),
    IndexCase("CVPR", 2023, 2000, lambda: CvfIndexProvider(
        SafeHttpClient(allowed_hosts={"openaccess.thecvf.com"}, timeout=120.0, **RETRY))),
    IndexCase("ICLR", 2024, 2200, lambda: IclrIndexProvider(
        SafeHttpClient(allowed_hosts={"proceedings.iclr.cc"}, timeout=120.0, **RETRY))),
    IndexCase("OSDI", 2024, 50, lambda: UsenixIndexProvider(
        SafeHttpClient(allowed_hosts={"www.usenix.org"}, timeout=120.0, **RETRY))),
)


@dataclass(frozen=True)
class Outcome:
    """What one attempt of a check observed; ``transient`` marks a failure worth a retry."""

    expected: Any
    observed: Any
    passed: bool | None
    transient: bool = False


def _without_urls(text: str) -> str:
    """Cut every URL down to its host; a query string can carry an API key."""
    return re.sub(r"https?://([^/\s?#'\"]+)[^\s'\"]*", r"\1", text)


def _is_transient(error: BaseException) -> bool:
    return isinstance(error, (RateLimited, NetworkTransient, httpx.TransportError)) or (
        isinstance(error, HttpStatusError) and error.status_code >= 500)


@dataclass
class Report:
    progress: Callable[[str], None]
    retry_pause: float = RETRY_PAUSE_SECONDS
    sleeper: Callable[[float], None] = time.sleep
    checks: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, expected: Any, observed: Any, passed: bool | None, *,
            retried: bool = False, upstream: bool = False) -> None:
        """Record one check; ``passed=None`` means skipped."""
        status = ("skipped" if passed is None else "passed" if passed
                  else "upstream_error" if upstream else "failed")
        self.checks.append({"check": name, "expected": expected, "observed": observed,
                            "status": status, "retried": retried})
        label = {"skipped": "skip", "passed": "ok  ", "failed": "FAIL",
                 "upstream_error": "UPST"}[status]
        self.progress(f"{label} {name}: {observed}{' (after a retry)' if retried else ''}")

    def run(self, name: str, attempt: Callable[[], Outcome], *, expected: Any) -> None:
        """Record one check; a transient failure is attempted once more after a pause."""
        for retried in (False, True):
            try:
                outcome = attempt()
            except Exception as exc:  # noqa: BLE001 - any failure is the finding
                text = _without_urls(str(exc) or type(exc).__name__)
                outcome = Outcome(expected, f"error: {text}", False, _is_transient(exc))
            if outcome.passed is not False or not outcome.transient or retried:
                break
            self.progress(f"wait {name}: {outcome.observed}; retrying in {self.retry_pause:g} s")
            self.sleeper(self.retry_pause)
        self.add(name, outcome.expected, outcome.observed, outcome.passed, retried=retried,
                 upstream=outcome.transient)

    def result(self) -> dict[str, Any]:
        def named(status: str) -> list[str]:
            return [item["check"] for item in self.checks if item["status"] == status]

        failed = named("failed")
        return {"status": "failed" if failed else "passed", "checked_at": date.today().isoformat(),
                "checks": self.checks, "failed": failed, "upstream_errors": named("upstream_error"),
                "retried": [item["check"] for item in self.checks if item["retried"]],
                "skipped": named("skipped")}


def _key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", html.unescape(value).casefold()))


def _crossref_json(client: SafeHttpClient, url: str, *, pause: float = CROSSREF_PAUSE_SECONDS,
                   sleeper: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """One Crossref request, paced and retried after HTTP 429 as Crossref asks."""
    for attempt in range(4):
        sleeper(pause)
        try:
            return client.get(url).json()
        except RateLimited as exc:
            if attempt == 3:
                raise
            sleeper(max(exc.retry_after_seconds or 0, 10.0 * (attempt + 1)))
    raise AssertionError("unreachable")


def _crossref_count(client: SafeHttpClient, filters: dict[str, str | tuple[str, ...]]) -> int:
    """Records matching ``filters``; a tuple value repeats the filter, which Crossref ORs."""
    query = urlencode({"filter": ",".join(
        f"{name}:{item}" for name, value in filters.items()
        for item in (value if isinstance(value, tuple) else (value,))), "rows": "0"})
    return int(_crossref_json(client, f"{CROSSREF}/works?{query}")["message"]["total-results"])


def _issn_outcome(crossref: SafeHttpClient, preset: VenuePreset, journal_year: int) -> Outcome:
    # Every ISSN must name the journal (or a former name in its aliases); together they must
    # have records, since a renamed journal keeps only its new ISSN in use.
    known = {_key(value) for value in (preset.name, *preset.aliases)}
    titles = [str((_crossref_json(crossref, f"{CROSSREF}/journals/{quote(issn)}")
                   ["message"].get("title")) or "") for issn in preset.issn]
    count = _crossref_count(crossref, {"issn": tuple(preset.issn),
                                       "from-pub-date": f"{journal_year}-01-01",
                                       "until-pub-date": f"{journal_year}-12-31"})
    return Outcome({"title": preset.name, f"{journal_year} records": "> 0"},
                   {"title": titles if len(titles) > 1 else titles[0],
                    f"{journal_year} records": count},
                   all(_key(title) in known for title in titles) and count > 0)


def _collection_outcome(crossref: SafeHttpClient, collection: str) -> Outcome:
    count = _crossref_count(crossref, {"alternative-id": collection})
    return Outcome("records > 0", count, count > 0)


def _openalex_outcome(openalex: OpenAlexClient, source: str, series_year: int) -> Outcome:
    payload = openalex._payload(  # one source record; the key stays out of output
        f"{openalex.endpoint.rsplit('/', 1)[0]}/sources/{source}?"
        + urlencode({"api_key": openalex.api_key}))
    resolved = str(payload.get("id") or "").rstrip("/").rsplit("/", 1)[-1]
    count = openalex.source_count(source, series_year)
    return Outcome({"id": source, f"{series_year} works": "> 0"},
                   {"id": resolved, "name": payload.get("display_name"),
                    f"{series_year} works": count},
                   resolved == source and count > 0)


def check_presets(report: Report, *, crossref: SafeHttpClient, openalex: OpenAlexClient | None,
                  journal_year: int, series_year: int,
                  presets: tuple[VenuePreset, ...] = PRESETS) -> None:
    for preset in presets:
        if preset.issn:
            report.run(f"preset {preset.id} ISSN {', '.join(preset.issn)}",
                       partial(_issn_outcome, crossref, preset, journal_year),
                       expected="journal title and records")
        for collection in getattr(preset, "collection_doi", ()):
            report.run(f"preset {preset.id} collection {collection}",
                       partial(_collection_outcome, crossref, collection),
                       expected="records > 0")
        for source in preset.openalex_source:
            name = f"preset {preset.id} OpenAlex {source}"
            if openalex is None:
                report.add(name, f"{series_year} works > 0", "no OPENALEX_API_KEY", None)
                continue
            report.run(name, partial(_openalex_outcome, openalex, source, series_year),
                       expected=f"{series_year} works > 0")


def _sampled(provider: Any, sample: int) -> Any:
    """Read the full listing but only the first ``sample`` paper pages."""
    if hasattr(provider, "fetch_details"):
        original_details = provider.fetch_details
        provider.fetch_details = lambda items, *a, **k: original_details(items[:sample], *a, **k)
    if hasattr(provider, "_index_entries"):
        original_entries = provider._index_entries

        def entries(*args: Any) -> tuple[int, list]:
            recognized, found = original_entries(*args)
            provider.canary_listed = recognized
            if len(found) != recognized:  # malformed listing records: report them as they are
                return recognized, found[:sample]
            # A consistent sample, so the provider does not report the unread papers as missing.
            return min(sample, recognized), found[:sample]
        provider._index_entries = entries
    return provider


def _index_outcome(case: IndexCase, sample: int) -> Outcome:
    request = DiscoveryRequest.from_spec({
        "name": "source check", "target": {"minimum": 1, "maximum": 1},
        "scope": {"venues": [{"name": case.venue, "kind": "conference"}],
                  "years": {"include": [case.year]}}})
    provider = _sampled(case.make(), sample)
    batch = provider.discover(replace(request))
    recognized = getattr(provider, "canary_listed",
                         sum(item.records_recognized for item in batch.coverage))
    with_abstract = sum(bool(candidate.abstract.strip()) for candidate in batch.candidates)
    listed_ok = recognized == case.minimum if case.exact else recognized >= case.minimum
    # Every sampled page must parse: a page that failed (even transiently) leaves a gap.
    wanted = max(1, min(sample, recognized))
    sample_ok = len(batch.candidates) >= wanted and with_abstract >= wanted
    codes = sorted({d.error_code for d in batch.diagnostics})
    return Outcome({"listed": f"{'==' if case.exact else '>='} {case.minimum}",
                    "sample with abstract": f">= {wanted}"},
                   {"listed": recognized, "sampled": len(batch.candidates),
                    "sample with abstract": with_abstract, "diagnostics": codes},
                   listed_ok and sample_ok, transient=bool(TRANSIENT & set(codes)))


def check_indexes(report: Report, *, sample: int,
                  cases: tuple[IndexCase, ...] = INDEX_CASES) -> None:
    for case in cases:
        report.run(f"index {case.venue} {case.year}", partial(_index_outcome, case, sample),
                   expected=f">= {case.minimum} listed")


def open_access_fetches() -> tuple[tuple[str, str], ...]:
    """The release smoke's fetches that deliver from any network, without a subscription."""
    spec = importlib.util.spec_from_file_location(
        "release_smoke_fetches", Path(__file__).with_name("release_smoke.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return tuple((label, reference) for label, reference, expected in module.FETCHES
                 if tuple(expected) == ("delivered",))


def _fetch_outcome(fetch: Fetch, reference: str, outputs: Callable[[], Path]) -> Outcome:
    code, payload = fetch(reference, outputs())
    observed = ("delivered" if payload.get("status") == "delivered"
                else str(payload.get("error_code") or f"exit {code}"))
    message = _without_urls(str(payload.get("message") or ""))
    return Outcome("delivered", observed if observed == "delivered" or not message
                   else {"outcome": observed, "message": message},
                   observed == "delivered", observed in TRANSIENT)


def check_fetches(report: Report, *, fetch: Fetch, workspace: Path,
                  cases: tuple[tuple[str, str], ...] | None = None) -> None:
    for label, reference in cases if cases is not None else open_access_fetches():
        slug = re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-")
        numbers = itertools.count(1)

        def outputs(slug: str = slug, numbers: Any = numbers) -> Path:
            # Each attempt writes to a fresh directory, so a retry never resumes a partial one.
            return workspace / slug / f"attempt-{next(numbers)}"

        report.run(f"fetch {label}", partial(_fetch_outcome, fetch, reference, outputs),
                   expected="delivered")


def cli_fetch(workspace: Path) -> Fetch:
    """``arp fetch`` in its own process, with throwaway roots and no keys or tokens."""
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("ARP_") and not key.endswith("_API_KEY")
                   and key != "MINERU_TOKEN"}
    environment.update(ARP_DATA_ROOT=str(workspace / "data"),
                       ARP_CONFIG_ROOT=str(workspace / "config"),
                       PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")

    def fetch(reference: str, output: Path) -> tuple[int, dict[str, Any]]:
        result = subprocess.run(
            [sys.executable, "-m", "acquire_research_papers", "fetch", "--input", reference,
             "--output", str(output)], capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=environment, cwd=workspace, timeout=900, check=False)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        try:
            payload = json.loads(lines[-1])
        except (IndexError, json.JSONDecodeError):
            payload = {"message": result.stderr.strip()[-300:]}
        return result.returncode, payload if isinstance(payload, dict) else {}
    return fetch


def _configured_openalex_key() -> str:
    from acquire_research_papers import configuration_commands
    from acquire_research_papers.credentials import API_PROVIDER_HOSTS
    from acquire_research_papers.paths import AppPaths

    manager = configuration_commands.credential_manager(AppPaths.default())
    return manager.api_provider("openalex", API_PROVIDER_HOSTS["openalex"]).optional() or ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=["presets", "indexes", "fetches"])
    parser.add_argument("--sample", type=int, default=3, help="paper pages read per index")
    parser.add_argument("--use-configured-keys", action="store_true",
                        help="without OPENALEX_API_KEY, read the key arp config stores")
    args = parser.parse_args(argv)
    report = Report(progress=lambda line: print(line, file=sys.stderr, flush=True))
    year = date.today().year
    if args.only in (None, "presets"):
        key = os.environ.get("OPENALEX_API_KEY", "").strip()
        if not key and args.use_configured_keys:
            key = _configured_openalex_key()
        openalex = OpenAlexClient(client=SafeHttpClient(allowed_hosts={"api.openalex.org"},
                                                        **RETRY), api_key=key) if key else None
        check_presets(report, crossref=SafeHttpClient(allowed_hosts={"api.crossref.org"},
                                                      timeout=60.0, **RETRY),
                      openalex=openalex, journal_year=year - 1, series_year=year - 2)
    if args.only in (None, "indexes"):
        check_indexes(report, sample=max(1, args.sample))
    if args.only in (None, "fetches"):
        workspace = Path(tempfile.mkdtemp(prefix="arp-source-check-"))
        try:
            check_fetches(report, fetch=cli_fetch(workspace), workspace=workspace)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
    result = report.result()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
