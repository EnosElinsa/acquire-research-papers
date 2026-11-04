"""Weekly live check that the built-in venue presets and official indexes still work.

  uv run python scripts/check_sources.py [--only presets|indexes] [--sample 3]

Presets: every ISSN must still name the preset's journal in Crossref and have records in the
last full year; every Crossref collection DOI must still have records; every OpenAlex source
must still resolve to itself and list works two years back (recent editions can lag). OpenAlex
checks need ``OPENALEX_API_KEY`` and are reported as skipped without it.

Indexes: each official proceedings index is read for one known year. A listing must still
yield close to its known paper count, and a few sample paper pages (``--sample``) must still
parse with an abstract, so a changed page layout shows up here before it reaches a user.

Prints one JSON object; exits 1 when any check fails.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from acquire_research_papers.acquisition.adapters.ijcai import IJCAI_HOSTS  # noqa: E402
from acquire_research_papers.discovery.contracts import DiscoveryRequest  # noqa: E402
from acquire_research_papers.discovery.official.acl import AclAnthologyDiscoveryProvider  # noqa: E402
from acquire_research_papers.discovery.official.archives import (  # noqa: E402
    CvfIndexProvider,
    NeuripsIndexProvider,
    PmlrIndexProvider,
)
from acquire_research_papers.discovery.official.ijcai import IjcaiDiscoveryProvider  # noqa: E402
from acquire_research_papers.discovery.openalex import OpenAlexClient  # noqa: E402
from acquire_research_papers.discovery.venue_presets import PRESETS, VenuePreset  # noqa: E402
from acquire_research_papers.http import RateLimited, SafeHttpClient  # noqa: E402

CROSSREF = "https://api.crossref.org"
CROSSREF_PAUSE_SECONDS = 1.0  # Crossref's public pool answers bursts with HTTP 429
RETRY = {"retries": 3, "backoff_seconds": 2.0}


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
)


@dataclass
class Report:
    progress: Callable[[str], None]
    checks: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, expected: Any, observed: Any, passed: bool | None) -> None:
        """Record one check; ``passed=None`` means skipped."""
        self.checks.append({"check": name, "expected": expected, "observed": observed,
                            "status": "skipped" if passed is None else
                            "passed" if passed else "failed"})
        label = {None: "skip", True: "ok  ", False: "FAIL"}[passed]
        self.progress(f"{label} {name}: {observed}")

    def result(self) -> dict[str, Any]:
        failed = [item["check"] for item in self.checks if item["status"] == "failed"]
        return {"status": "failed" if failed else "passed", "checked_at": date.today().isoformat(),
                "checks": self.checks, "failed": failed,
                "skipped": [item["check"] for item in self.checks if item["status"] == "skipped"]}


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


def check_presets(report: Report, *, crossref: SafeHttpClient, openalex: OpenAlexClient | None,
                  journal_year: int, series_year: int,
                  presets: tuple[VenuePreset, ...] = PRESETS) -> None:
    dates = {"from-pub-date": f"{journal_year}-01-01", "until-pub-date": f"{journal_year}-12-31"}
    for preset in presets:
        if preset.issn:
            # Every ISSN must name the journal (or a former name in its aliases); together they
            # must have records, since a renamed journal keeps only its new ISSN in use.
            name = f"preset {preset.id} ISSN {', '.join(preset.issn)}"
            known = {_key(value) for value in (preset.name, *preset.aliases)}
            try:
                titles = [str((_crossref_json(crossref, f"{CROSSREF}/journals/{quote(issn)}")
                               ["message"].get("title")) or "") for issn in preset.issn]
                count = _crossref_count(crossref, {"issn": tuple(preset.issn), **dates})
            except Exception as exc:  # noqa: BLE001 - any failure is the finding
                report.add(name, "journal title and records", f"error: {exc}", False)
            else:
                report.add(name, {"title": preset.name, f"{journal_year} records": "> 0"},
                           {"title": titles if len(titles) > 1 else titles[0],
                            f"{journal_year} records": count},
                           all(_key(title) in known for title in titles) and count > 0)
        for collection in getattr(preset, "collection_doi", ()):
            name = f"preset {preset.id} collection {collection}"
            try:
                count = _crossref_count(crossref, {"alternative-id": collection})
            except Exception as exc:  # noqa: BLE001
                report.add(name, "records", f"error: {exc}", False)
                continue
            report.add(name, "records > 0", count, count > 0)
        for source in preset.openalex_source:
            name = f"preset {preset.id} OpenAlex {source}"
            if openalex is None:
                report.add(name, f"{series_year} works > 0", "no OPENALEX_API_KEY", None)
                continue
            try:
                payload = openalex._payload(  # one source record; the key stays out of output
                    f"{openalex.endpoint.rsplit('/', 1)[0]}/sources/{source}?"
                    + urlencode({"api_key": openalex.api_key}))
                resolved = str(payload.get("id") or "").rstrip("/").rsplit("/", 1)[-1]
                count = openalex.source_count(source, series_year)
            except Exception as exc:  # noqa: BLE001
                report.add(name, f"{series_year} works > 0", f"error: {exc}", False)
                continue
            report.add(name, {"id": source, f"{series_year} works": "> 0"},
                       {"id": resolved, "name": payload.get("display_name"),
                        f"{series_year} works": count},
                       resolved == source and count > 0)


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


def check_indexes(report: Report, *, sample: int,
                  cases: tuple[IndexCase, ...] = INDEX_CASES) -> None:
    for case in cases:
        name = f"index {case.venue} {case.year}"
        request = DiscoveryRequest.from_spec({
            "name": "source check", "target": {"minimum": 1, "maximum": 1},
            "scope": {"venues": [{"name": case.venue, "kind": "conference"}],
                      "years": {"include": [case.year]}}})
        try:
            provider = _sampled(case.make(), sample)
            batch = provider.discover(replace(request))
        except Exception as exc:  # noqa: BLE001
            report.add(name, f">= {case.minimum} listed", f"error: {exc}", False)
            continue
        recognized = getattr(provider, "canary_listed",
                             sum(item.records_recognized for item in batch.coverage))
        with_abstract = sum(bool(candidate.abstract.strip()) for candidate in batch.candidates)
        listed_ok = recognized == case.minimum if case.exact else recognized >= case.minimum
        sample_ok = with_abstract >= min(sample, len(batch.candidates)) and bool(batch.candidates)
        report.add(name, {"listed": f"{'==' if case.exact else '>='} {case.minimum}",
                          "sample with abstract": f">= {min(sample, len(batch.candidates))}"},
                   {"listed": recognized, "sampled": len(batch.candidates),
                    "sample with abstract": with_abstract,
                    "diagnostics": sorted({d.error_code for d in batch.diagnostics})},
                   listed_ok and sample_ok)


def _configured_openalex_key() -> str:
    from acquire_research_papers import configuration_commands
    from acquire_research_papers.credentials import API_PROVIDER_HOSTS
    from acquire_research_papers.paths import AppPaths

    manager = configuration_commands.credential_manager(AppPaths.default())
    return manager.api_provider("openalex", API_PROVIDER_HOSTS["openalex"]).optional() or ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=["presets", "indexes"])
    parser.add_argument("--sample", type=int, default=3, help="paper pages read per index")
    parser.add_argument("--use-configured-keys", action="store_true",
                        help="without OPENALEX_API_KEY, read the key arp config stores")
    args = parser.parse_args(argv)
    report = Report(progress=lambda line: print(line, file=sys.stderr, flush=True))
    year = date.today().year
    if args.only != "indexes":
        key = os.environ.get("OPENALEX_API_KEY", "").strip()
        if not key and args.use_configured_keys:
            key = _configured_openalex_key()
        openalex = OpenAlexClient(client=SafeHttpClient(allowed_hosts={"api.openalex.org"},
                                                        **RETRY), api_key=key) if key else None
        check_presets(report, crossref=SafeHttpClient(allowed_hosts={"api.crossref.org"},
                                                      timeout=60.0, **RETRY),
                      openalex=openalex, journal_year=year - 1, series_year=year - 2)
    if args.only != "presets":
        check_indexes(report, sample=max(1, args.sample))
    result = report.result()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
