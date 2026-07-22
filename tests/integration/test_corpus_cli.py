from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from acquire_research_papers.cli import (
    Application,
    _production_discovery_enrichers,
    _production_discovery_providers,
    run_cli,
)
from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    DiscoveryBatch,
    DiscoveryCapabilities,
    DiscoveryDiagnostic,
    DiscoveryRequest,
)
from acquire_research_papers.discovery.coordinator import DiscoveryCoordinator
from acquire_research_papers.discovery.corpus import CorpusDiscoveryWorkflow
from acquire_research_papers.discovery.providers import CrossrefVenueDiscoveryProvider


def test_discover_corpus_writes_review_evidence_without_acquiring(
    tmp_path: Path,
    capsys,
) -> None:
    spec = tmp_path / "job.yaml"
    spec.write_text(
        "mode: corpus\nname: split\ntarget:\n  minimum: 1\n"
        "  preferred: 1\n  maximum: 2\n",
        encoding="utf-8",
    )
    candidate = CandidateMetadata(
        "high",
        "High",
        2026,
        "Test",
        0.91,
        True,
        ("title", "abstract"),
        doi="10.1000/high",
        abstract="Relevant abstract",
    )
    workflow = CorpusDiscoveryWorkflow(
        discoverer=lambda request: DiscoveryBatch(
            (candidate,), covered_slices=(f"fake:{request.name}",)
        ),
    )
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        corpus_discovery=workflow,
    )
    output = tmp_path / "output"

    exit_code = run_cli(
        ["discover", "corpus", "--spec", str(spec), "--output", str(output)],
        application=application,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "review_required"
    assert Path(payload["evidence_packets"]).is_file()
    assert Path(payload["coverage"]).is_file()
    assert payload["reviewable"] == 1
    assert not (output / "selected-papers.jsonl").exists()
    assert not (output / "selection-manifest.json").exists()
    assert not (output / "acquisition-manifest.jsonl").exists()
    assert not (output / "manual-download.csv").exists()
    assert not list(output.rglob("*.pdf"))
    assert not list(output.rglob("*.bib"))
    assert "delivered" not in payload
    assert "deferred" not in payload


def test_discover_corpus_persists_sanitized_provider_diagnostics(
    tmp_path: Path,
    capsys,
) -> None:
    spec = tmp_path / "job.yaml"
    spec.write_text(
        "mode: corpus\nname: diagnostics\ntarget:\n  minimum: 1\n  maximum: 1\n",
        encoding="utf-8",
    )
    diagnostic = DiscoveryDiagnostic(
        "official",
        "index",
        "page_contract_changed",
        "official index did not match its expected structure",
        venue="Invented Venue",
        year=2026,
    )
    workflow = CorpusDiscoveryWorkflow(
        discoverer=lambda _: DiscoveryBatch(diagnostics=(diagnostic,)),
    )
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        corpus_discovery=workflow,
    )
    output = tmp_path / "output"

    exit_code = run_cli(
        ["discover", "corpus", "--spec", str(spec), "--output", str(output)],
        application=application,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "coverage_incomplete"
    rows = [
        json.loads(line)
        for line in Path(payload["discovery_errors"]).read_text(encoding="utf-8").splitlines()
    ]
    assert rows == [
        {
            "error_code": "page_contract_changed",
            "message": "official index did not match its expected structure",
            "phase": "index",
            "provider_id": "official",
            "retryable": False,
            "url": "",
            "venue": "Invented Venue",
            "year": 2026,
        }
    ]


@dataclass
class FakeProviderForVenue:
    venue: str

    def capabilities(self) -> DiscoveryCapabilities:
        return DiscoveryCapabilities(
            provider_id="invented-provider",
            source_class="official_index",
            venue_aliases=frozenset({self.venue}),
        )

    def discover(self, request: DiscoveryRequest) -> DiscoveryBatch:
        assert [venue.name for venue in request.venues] == [self.venue]
        candidate = CandidateMetadata(
            "invented-1",
            "Evolutionary Invented Paper",
            2026,
            self.venue,
            0.0,
            True,
            ("title", "abstract"),
            doi="10.1000/invented",
            abstract="Evolutionary methods for an invented domain.",
            provenance={"source": "invented-provider"},
        )
        return DiscoveryBatch((candidate,), covered_slices=("invented-provider:2026",))


def test_fake_provider_extends_corpus_without_core_venue_changes(
    tmp_path: Path,
    capsys,
) -> None:
    venue = "Invented Proceedings"
    application = Application.for_test(
        app_root=tmp_path / "app",
        repository_root=tmp_path / "repository",
        corpus_discovery=CorpusDiscoveryWorkflow(
            discoverer=DiscoveryCoordinator([FakeProviderForVenue(venue)]).discover
        ),
    )
    spec = tmp_path / "invented.yaml"
    spec.write_text(
        "mode: corpus\nname: invented\ntarget:\n  minimum: 1\n  maximum: 1\n"
        "scope:\n  venues:\n    - name: Invented Proceedings\n"
        "  years:\n    include: [2026]\n"
        "  topics:\n    include: [evolutionary]\n",
        encoding="utf-8",
    )
    output = tmp_path / "run"

    assert run_cli(
        ["discover", "corpus", "--spec", str(spec), "--output", str(output)],
        application=application,
    ) == 0
    capsys.readouterr()

    evidence = (output / "evidence-packets.jsonl").read_text(encoding="utf-8")
    assert venue in evidence
    assert "invented-provider:2026" in (
        output / "discovery-manifest.json"
    ).read_text(encoding="utf-8")


def test_production_provider_registry_fails_closed_without_optional_keys() -> None:
    crossref = SimpleNamespace(search=lambda *_args, **_kwargs: None)

    providers = _production_discovery_providers(
        crossref=crossref,
        acl_client=None,
        ijcai_client=None,
        environment={},
    )

    assert [provider.capabilities().provider_id for provider in providers] == [
        "crossref",
        "acl-anthology",
        "ijcai-proceedings",
    ]
    assert isinstance(providers[0], CrossrefVenueDiscoveryProvider)


def test_production_registry_uses_keyless_doi_enrichment() -> None:
    enrichers = _production_discovery_enrichers(environment={})

    assert [enricher.capabilities().provider_id for enricher in enrichers] == [
        "semantic-scholar"
    ]
