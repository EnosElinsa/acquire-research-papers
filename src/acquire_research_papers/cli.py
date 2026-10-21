from __future__ import annotations

import argparse
import json
import math
import os
import sys
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acquire_research_papers import __version__
from acquire_research_papers.acquisition.adapters.acm import AcmDigitalLibraryAdapter
from acquire_research_papers.acquisition.adapters.acl import AclAnthologyAdapter
from acquire_research_papers.acquisition.adapters.ieee import (
    IeeeBridge,
    IeeeBridgeError,
    IeeeXploreAdapter,
)
from acquire_research_papers.acquisition.adapters.ijcai import IjcaiProceedingsAdapter
from acquire_research_papers.acquisition.adapters.elsevier_api import (
    ELSEVIER_API_HOST,
    ElsevierApiError,
    ElsevierSearchClient,
)
from acquire_research_papers.acquisition.adapters.sciencedirect import ScienceDirectAdapter
from acquire_research_papers.acquisition.base import AccessRequired, PageContractChanged, SourceAdapter
from acquire_research_papers.acquisition.corpus import CorpusAcquisitionWorkflow
from acquire_research_papers.acquisition.manual_handoff import (
    ManualBrowserOpenError,
    ManualDownloadAmbiguous,
    ManualDownloadTimeout,
    ManualHandoffWorkflow,
    ManualSelectionWorkflow,
    ManualSourceChanged,
    PdfIdentityMismatch,
)
from acquire_research_papers.acquisition.router import AdapterRouter
from acquire_research_papers.artifacts import InvalidPdfError, sha256_file
from acquire_research_papers.bibliography import BibMissing, MetadataMismatch
from acquire_research_papers.delivery import DeliveryResult, GenericDelivery
from acquire_research_papers.discovery.contracts import (
    CandidateMetadata,
    DiscoveryEnricher,
    DiscoveryProvider,
)
from acquire_research_papers.discovery.coordinator import DiscoveryCoordinator
from acquire_research_papers.discovery.corpus import CorpusDiscoveryWorkflow
from acquire_research_papers.discovery.review import CorpusReviewWorkflow
from acquire_research_papers.discovery.crossref import CrossrefClient
from acquire_research_papers.discovery.openalex import OpenAlexClient
from acquire_research_papers.discovery.official import (
    AclAnthologyDiscoveryProvider,
    IjcaiDiscoveryProvider,
)
from acquire_research_papers.discovery.providers import (
    CrossrefVenueDiscoveryProvider,
    DoiBatchEnrichmentProvider,
    QueryApiProvider,
)
from acquire_research_papers.discovery.semantic_scholar import (
    SemanticScholarClient,
    SemanticScholarRequestPacer,
)
from acquire_research_papers.credentials import (
    API_PROVIDER_HOSTS,
    ApiKeyLoadError,
    CredentialStatusError,
    DpapiApiKeyProvider,
)
from acquire_research_papers.http import NetworkTransient, RateLimited, SafeHttpClient
from acquire_research_papers.file_credentials import API_KEYS
from acquire_research_papers.mineru import (
    MineruCache,
    MineruCliRunner,
    MineruExtractionError,
    MineruRateLimited,
    MineruResult,
)
from acquire_research_papers.models import PaperStatus
from acquire_research_papers.paths import AppPaths, ensure_outside_repository
from acquire_research_papers.registry import Registry
from acquire_research_papers.research.evidence_workflow import ResearchEvidenceWorkflow
from acquire_research_papers.research.fulltext import ResearchFullTextWorkflow
from acquire_research_papers.research.review import ResearchReviewWorkflow
from acquire_research_papers.research.workflow import ResearchDiscoverer, ResearchWorkflow
from acquire_research_papers.resolver import AmbiguousInput, Resolver
from acquire_research_papers.selection import SelectionRecord, SelectionStore
from acquire_research_papers.specs import (
    SpecValidationError,
    load_corpus_spec,
    load_research_brief,
)


_RUNTIME_SCRIPT_NAMES = frozenset(
    {
        "ieee-playwright.mjs",
        "install-playwright.ps1",
        "read-browser-credential.ps1",
        "read-institution-profile.ps1",
        "read-mineru-token.ps1",
        "read-elsevier-api-key.ps1",
        "read-discovery-api-key.ps1",
        "credential-status.ps1",
        "secret-store.ps1",
    }
)

_IEEE_ACCESS_PHASES = frozenset(
    {
        "authentication-not-complete",
        "authentication-result",
        "credential-read",
        "unexpected-auth-host",
        "carsi-school",
        "carsi-institution",
        "carsi-login",
        "institution-username",
        "institution-password",
        "institution-login",
        "attribute-release-controls",
        "attribute-release-required",
        "institutional-return",
        "download-after-auth",
        "access-required",
        "manual-login-timeout",
        "assisted-login-timeout",
    }
)


def _is_ieee_access_phase(phase: str) -> bool:
    return phase in _IEEE_ACCESS_PHASES


def _resolve_script_root(repository_root: Path, package_root: Path) -> Path:
    for candidate in (repository_root / "scripts", package_root / "_scripts"):
        if all((candidate / name).is_file() for name in _RUNTIME_SCRIPT_NAMES):
            return candidate.resolve()
    raise RuntimeError("acquire-research-papers runtime scripts are missing")


def _production_discovery_providers(
    *,
    crossref: CrossrefClient,
    acl_client: SafeHttpClient,
    ijcai_client: SafeHttpClient,
    environment: Mapping[str, str] | None = None,
    api_keys: Mapping[str, str] | None = None,
    semantic_request_pacer: SemanticScholarRequestPacer | None = None,
) -> list[DiscoveryProvider]:
    providers: list[DiscoveryProvider] = [
        CrossrefVenueDiscoveryProvider(crossref.search),
        AclAnthologyDiscoveryProvider(client=acl_client),
        IjcaiDiscoveryProvider(client=ijcai_client),
    ]
    configured = os.environ if environment is None else environment
    stored = api_keys or {}
    openalex_key = (
        configured.get("OPENALEX_API_KEY", "").strip()
        or stored.get("openalex", "").strip()
    )
    if openalex_key:
        openalex = OpenAlexClient(
            client=SafeHttpClient(allowed_hosts={"api.openalex.org"}),
            api_key=openalex_key,
        )
        providers.append(QueryApiProvider("openalex", openalex.corpus_searcher))
    semantic_key = (
        configured.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
        or stored.get("semantic_scholar", "").strip()
    )
    if semantic_key:
        semantic = SemanticScholarClient(
            client=SafeHttpClient(allowed_hosts={"api.semanticscholar.org"}),
            api_key=semantic_key,
            request_pacer=semantic_request_pacer,
        )
        providers.append(
            QueryApiProvider("semantic-scholar-search", semantic.corpus_searcher)
        )
    return providers


def _production_discovery_enrichers(
    *,
    environment: Mapping[str, str] | None = None,
    api_keys: Mapping[str, str] | None = None,
    semantic_request_pacer: SemanticScholarRequestPacer | None = None,
) -> list[DiscoveryEnricher]:
    configured = os.environ if environment is None else environment
    stored = api_keys or {}
    semantic_key = (
        configured.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
        or stored.get("semantic_scholar", "").strip()
    )
    openalex_key = (
        configured.get("OPENALEX_API_KEY", "").strip()
        or stored.get("openalex", "").strip()
    )
    semantic = SemanticScholarClient(
        client=SafeHttpClient(allowed_hosts={"api.semanticscholar.org"}),
        api_key=semantic_key or None,
        request_pacer=semantic_request_pacer,
    )
    enrichers: list[DiscoveryEnricher] = [
        DoiBatchEnrichmentProvider(
            "semantic-scholar",
            semantic.lookup_dois,
            pause_seconds=1.0,
        )
    ]
    if openalex_key:
        openalex = OpenAlexClient(
            client=SafeHttpClient(allowed_hosts={"api.openalex.org"}),
            api_key=openalex_key,
        )
        enrichers.append(
            DoiBatchEnrichmentProvider(
                "openalex",
                openalex.lookup_dois,
                batch_size=100,
                pause_seconds=0.1,
            )
        )
    return enrichers


def _supports_dpapi() -> bool:
    return os.name == "nt"


def _load_optional_discovery_api_keys(
    *,
    script_root: Path,
    secret_path: Path,
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    if not _supports_dpapi():
        return {}
    configured = os.environ if environment is None else environment
    overrides = {
        "semantic_scholar": "SEMANTIC_SCHOLAR_API_KEY",
        "openalex": "OPENALEX_API_KEY",
    }
    keys: dict[str, str] = {}
    for provider, variable in overrides.items():
        if configured.get(variable, "").strip():
            continue
        value = DpapiApiKeyProvider(
            provider=provider,
            expected_host=API_PROVIDER_HOSTS[provider],
            script=script_root / "read-discovery-api-key.ps1",
            secret_path=secret_path,
        ).optional()
        if value:
            keys[provider] = value
    return keys


def _default_credential_status(*, env_file: Path | None = None) -> dict[str, bool]:
    from acquire_research_papers import configuration_commands as config
    paths = config.runtime_paths()
    return config.credential_manager(paths, env_file=env_file).status()


def _stderr_discovery_progress(event: str, details: Mapping[str, object]) -> None:
    print(
        json.dumps({"event": event, **details}, ensure_ascii=False, sort_keys=True),
        file=sys.stderr,
        flush=True,
    )


@dataclass
class Application:
    paths: AppPaths
    repository_root: Path
    registry: Registry
    resolver: Resolver
    corpus_discovery: CorpusDiscoveryWorkflow | None = None
    corpus_acquisition: CorpusAcquisitionWorkflow | None = None
    research_workflow: ResearchWorkflow | None = None
    research_fulltext: ResearchFullTextWorkflow | None = None
    mineru_cache: MineruCache | None = None
    manual_handoff: ManualHandoffWorkflow | None = None
    manual_selection: ManualSelectionWorkflow | None = None
    discovery_coordinator: DiscoveryCoordinator | None = None

    @classmethod
    def for_test(
        cls,
        *,
        app_root: Path,
        repository_root: Path,
        adapter: SourceAdapter | None = None,
        corpus_discovery: CorpusDiscoveryWorkflow | None = None,
        corpus_acquisition: CorpusAcquisitionWorkflow | None = None,
        research_workflow: ResearchWorkflow | None = None,
        research_fulltext: ResearchFullTextWorkflow | None = None,
        mineru_cache: MineruCache | None = None,
        manual_handoff: ManualHandoffWorkflow | None = None,
        manual_selection: ManualSelectionWorkflow | None = None,
    ) -> Application:
        paths = AppPaths.for_root(app_root)
        paths.create_directories()
        if adapter is None:
            router = AdapterRouter()
        else:
            hosts = getattr(adapter, "production_hosts", frozenset())
            router = AdapterRouter({host: adapter.name for host in hosts}, [adapter])
        application = cls(
            paths=paths,
            repository_root=repository_root.resolve(),
            registry=Registry(paths.registry),
            resolver=Resolver(router),
            corpus_discovery=corpus_discovery,
            corpus_acquisition=corpus_acquisition,
            research_workflow=research_workflow,
            research_fulltext=research_fulltext,
            mineru_cache=mineru_cache,
            manual_handoff=manual_handoff,
            manual_selection=manual_selection,
        )
        return application

    @classmethod
    def default(
        cls,
        *,
        accept_ieee_attribute_release: bool = True,
        discovery_progress: Callable[[str, Mapping[str, object]], None] | None = None,
        load_discovery_api_keys: bool = True,
        ieee_profile: str | None = None,
        env_file: Path | None = None,
    ) -> Application:
        paths = AppPaths.default()
        paths.create_directories()
        repository_root = Path(__file__).resolve().parents[2]
        script_root = _resolve_script_root(repository_root, Path(__file__).resolve().parent)
        acl = AclAnthologyAdapter(SafeHttpClient(allowed_hosts={"aclanthology.org"}))
        ijcai = IjcaiProceedingsAdapter(SafeHttpClient(allowed_hosts={"www.ijcai.org"}))
        acm = AcmDigitalLibraryAdapter.for_production()
        sciencedirect = ScienceDirectAdapter.for_production()
        from acquire_research_papers import configuration_commands
        manager = configuration_commands.credential_manager(paths, env_file=env_file)
        store = configuration_commands.store_for(paths, manager=manager)
        configuration_commands.migrate_legacy(store, paths)
        profile = store.get(ieee_profile) if ieee_profile else store.active()
        if profile:
            bridge = configuration_commands.bridge_for(profile, paths, manager=manager)
            bridge.accept_attribute_release = (bridge.accept_attribute_release
                                               and accept_ieee_attribute_release)
        else:
            bridge = IeeeBridge(
                script=script_root / "ieee-playwright.mjs",
                profile_root=paths.profiles / "ieee",
                dependency_root=paths.dependencies,
                work_root=paths.runs,
                secret_path=paths.secrets / "secrets.clixml",
                accept_attribute_release=accept_ieee_attribute_release,
                data_root=paths.registry.parent.parent,
            )
        ieee = IeeeXploreAdapter(bridge)
        crossref = CrossrefClient(
            client=SafeHttpClient(allowed_hosts={"api.crossref.org"}),
        )
        discovery_api_keys = (
            {provider: manager.api_provider(provider, API_PROVIDER_HOSTS[provider]).optional() or ""
             for provider in ("semantic_scholar", "openalex")}
            if load_discovery_api_keys
            else {}
        )
        semantic_request_pacer = SemanticScholarRequestPacer()
        discovery_providers = _production_discovery_providers(
            crossref=crossref,
            acl_client=acl.client,
            ijcai_client=ijcai.client,
            api_keys=discovery_api_keys,
            semantic_request_pacer=semantic_request_pacer,
        )
        discovery_enrichers = _production_discovery_enrichers(
            api_keys=discovery_api_keys,
            semantic_request_pacer=semantic_request_pacer,
        )
        mineru_runner = MineruCliRunner(
            token_provider=manager.api_provider("mineru", "mineru.net")
        )
        mineru_cache = MineruCache(paths.cache, runner=mineru_runner)
        elsevier_key = manager.api_provider("elsevier", ELSEVIER_API_HOST)
        coordinator = DiscoveryCoordinator(discovery_providers, enrichers=discovery_enrichers,
                                           progress=discovery_progress)
        manual_handoff = ManualHandoffWorkflow(
            resolver=ElsevierSearchClient(
                client=SafeHttpClient(allowed_hosts={ELSEVIER_API_HOST}),
                key_provider=elsevier_key,
            ),
            opener=webbrowser.open,
        )
        application = cls(
            paths=paths,
            repository_root=repository_root,
            registry=Registry(paths.registry),
            resolver=Resolver(
                AdapterRouter.with_defaults([acl, ijcai, ieee, acm, sciencedirect])
            ),
            corpus_discovery=CorpusDiscoveryWorkflow(
                discoverer=coordinator.discover,
                progress=discovery_progress,
            ),
            corpus_acquisition=None,
            research_workflow=None,
            research_fulltext=None,
            mineru_cache=mineru_cache,
            manual_handoff=manual_handoff,
            manual_selection=ManualSelectionWorkflow(opener=webbrowser.open),
            discovery_coordinator=coordinator,
        )
        application.corpus_acquisition = CorpusAcquisitionWorkflow(
            acquirer=application.acquire_selected
        )
        research_searchers = [crossref.corpus_searcher]
        research_graph_expanders = []
        semantic_key = (
            os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()
            or discovery_api_keys.get("semantic_scholar", "").strip()
        )
        semantic_research = SemanticScholarClient(
            client=SafeHttpClient(allowed_hosts={"api.semanticscholar.org"}),
            api_key=semantic_key or None,
            request_pacer=semantic_request_pacer,
        )
        research_graph_expanders.append(semantic_research.expand)
        if semantic_key:
            research_searchers.append(semantic_research.corpus_searcher)
        openalex_key = (
            os.environ.get("OPENALEX_API_KEY", "").strip()
            or discovery_api_keys.get("openalex", "").strip()
        )
        if openalex_key:
            openalex_research = OpenAlexClient(
                client=SafeHttpClient(allowed_hosts={"api.openalex.org"}),
                api_key=openalex_key,
            )
            research_searchers.append(openalex_research.corpus_searcher)
            research_graph_expanders.append(openalex_research.expand)
        application.research_workflow = ResearchWorkflow(
            discoverer=ResearchDiscoverer(
                research_searchers,
                graph_expanders=research_graph_expanders,
            ),
            mineru_cache=mineru_cache,
        )
        application.research_fulltext = ResearchFullTextWorkflow(
            acquisition=application.corpus_acquisition,
            mineru_cache=mineru_cache,
        )
        return application

    def _deliver_pair(
        self,
        *,
        pair,
        destination: Path,
        source: str,
        provenance_extra: dict[str, Any] | None = None,
        registry_payload: dict[str, Any] | None = None,
        relative_paths: tuple[Path, Path, Path] | None = None,
    ) -> DeliveryResult:
        metadata = pair.document.metadata
        paper_id = self.registry.upsert_paper(
            title=metadata.title,
            doi=metadata.doi,
            year=metadata.year,
            first_author=metadata.authors[0] if metadata.authors else None,
            venue=metadata.venue,
        )
        status = self.registry.status(paper_id)
        if status is PaperStatus.DISCOVERED:
            self.registry.transition(paper_id, PaperStatus.AUTO_ACCEPTED)
            status = PaperStatus.AUTO_ACCEPTED
        if status is PaperStatus.AUTO_ACCEPTED:
            self.registry.transition(paper_id, PaperStatus.RESOLVING)
            status = PaperStatus.RESOLVING

        if status is PaperStatus.RESOLVING:
            self.registry.transition(paper_id, PaperStatus.DOWNLOADED)
            status = PaperStatus.DOWNLOADED
        result = GenericDelivery(destination).deliver(
            pair=pair,
            paper_id=paper_id,
            provenance_extra=provenance_extra,
            relative_paths=relative_paths,
        )
        if status is PaperStatus.DOWNLOADED:
            self.registry.transition(paper_id, PaperStatus.PAIR_VERIFIED)
            status = PaperStatus.PAIR_VERIFIED
        if status is PaperStatus.PAIR_VERIFIED:
            self.registry.transition(paper_id, PaperStatus.DELIVERED)
        self.registry.record_artifact(
            paper_id,
            kind="pdf",
            path=result.pdf,
            sha256=sha256_file(result.pdf),
            source_url=pair.document.pdf_url,
        )
        self.registry.record_artifact(
            paper_id,
            kind="bibtex",
            path=result.bibtex,
            sha256=sha256_file(result.bibtex),
            source_url=pair.document.bibtex_url,
        )
        self.registry.record_artifact(
            paper_id,
            kind="provenance",
            path=result.provenance,
            sha256=sha256_file(result.provenance),
            source_url=pair.document.metadata.landing_url,
        )
        self.registry.record_provenance(
            paper_id,
            source=source,
            source_url=pair.document.metadata.landing_url,
            payload={
                "pdf": str(result.pdf),
                "bibtex": str(result.bibtex),
                "provenance": str(result.provenance),
                **(registry_payload or {}),
            },
        )
        return result

    def fetch(self, value: str, output: Path) -> DeliveryResult:
        try:
            destination = ensure_outside_repository(output, self.repository_root)
        except ValueError as exc:
            raise AmbiguousInput(str(exc)) from exc
        cached = self.registry.verified_delivery(value, destination)
        if cached:
            return DeliveryResult(
                pdf=cached["pdf"],
                bibtex=cached["bibtex"],
                provenance=cached["provenance"],
            )
        resolved = self.resolver.resolve(value)
        pair = resolved.adapter.acquire(resolved.document)
        return self._deliver_pair(
            pair=pair,
            destination=destination,
            source=resolved.adapter.name,
        )

    def manual_fetch(
        self,
        value: str,
        output: Path,
        *,
        watch: Path | None,
        timeout_seconds: float,
        open_browser: bool,
        pdf: Path | None,
        bibtex: Path | None,
        notifier,
    ) -> DeliveryResult:
        if (pdf is None) != (bibtex is None):
            raise AmbiguousInput("--pdf and --bibtex must be supplied together")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise AmbiguousInput("--timeout must be positive")
        if pdf is not None and bibtex is not None:
            if not pdf.is_file() or not bibtex.is_file():
                raise AmbiguousInput("--pdf and --bibtex must both name existing files")
        else:
            watch_root = (watch or (Path.home() / "Downloads")).resolve()
            if not watch_root.is_dir():
                raise AmbiguousInput("--watch must name an existing directory")
        if self.manual_handoff is None:
            raise AccessRequired("manual publisher handoff is not configured")
        try:
            destination = ensure_outside_repository(output, self.repository_root)
        except ValueError as exc:
            raise AmbiguousInput(str(exc)) from exc
        cached = self.registry.verified_delivery(value, destination)
        if cached:
            return DeliveryResult(
                pdf=cached["pdf"],
                bibtex=cached["bibtex"],
                provenance=cached["provenance"],
            )
        acquired = self.manual_handoff.acquire(
            value,
            watch=watch,
            timeout_seconds=timeout_seconds,
            open_browser=open_browser,
            pdf=pdf,
            bibtex=bibtex,
            notifier=notifier,
        )
        selection = acquired.selection
        provenance = {
            "acquisition_method": "manual_publisher_download",
            "metadata_source_url": acquired.record.metadata_url,
            "metadata_author_scope": acquired.record.author_scope,
            "source_pdf_filename": selection.source_pdf.name,
            "source_bibtex_filename": selection.source_bibtex.name,
        }
        return self._deliver_pair(
            pair=selection.pair,
            destination=destination,
            source="manual_publisher_download",
            provenance_extra=provenance,
            registry_payload=provenance,
        )

    def export_markdown(self, pdf: Path, output: Path) -> tuple[MineruResult, Path, Path]:
        if self.mineru_cache is None:
            raise MineruExtractionError("MinerU cache is not configured")
        destination = ensure_outside_repository(output, self.repository_root)
        result = self.mineru_cache.parse(pdf.resolve())
        exported = self.mineru_cache.export(result, destination)
        markdown = exported / result.markdown.relative_to(result.output_dir)
        return result, exported, markdown

    def manual_fetch_selected(
        self,
        selection_manifest: Path,
        selection_id: str,
        output: Path,
        *,
        watch: Path | None,
        timeout_seconds: float,
        open_browser: bool,
        pdf: Path | None,
        bibtex: Path | None,
        notifier,
    ) -> DeliveryResult:
        try:
            store = SelectionStore.load(selection_manifest)
        except ValueError as exc:
            raise AmbiguousInput(str(exc)) from exc
        matches = [record for record in store.records if record.selection_id == selection_id]
        if len(matches) != 1:
            raise AmbiguousInput("--key must match exactly one frozen selection ID")
        record = matches[0]
        if (pdf is None) != (bibtex is None):
            raise AmbiguousInput("--pdf and --bibtex must be supplied together")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise AmbiguousInput("--timeout must be positive")
        if pdf is not None and bibtex is not None:
            if not pdf.is_file() or not bibtex.is_file():
                raise AmbiguousInput("--pdf and --bibtex must both name existing files")
        else:
            watch_root = (watch or (Path.home() / "Downloads")).resolve()
            if not watch_root.is_dir():
                raise AmbiguousInput("--watch must name an existing directory")
        if self.manual_selection is None:
            raise AccessRequired("selected-paper manual handoff is not configured")
        try:
            destination = ensure_outside_repository(output, self.repository_root)
        except ValueError as exc:
            raise AmbiguousInput(str(exc)) from exc
        selection = self.manual_selection.acquire(
            record,
            watch=watch,
            timeout_seconds=timeout_seconds,
            open_browser=open_browser,
            pdf=pdf,
            bibtex=bibtex,
            notifier=notifier,
        )
        provenance = {
            "selection_id": record.selection_id,
            "acquisition_method": "manual_publisher_download",
            "source_pdf_filename": selection.source_pdf.name,
            "source_bibtex_filename": selection.source_bibtex.name,
        }
        if selection.pair.document.metadata.year != record.year:
            provenance.update(
                {
                    "selection_year": record.year,
                    "selection_publication_date": record.publication_date,
                    "publisher_bibliographic_year": selection.pair.document.metadata.year,
                }
            )
        return self._deliver_pair(
            pair=selection.pair,
            destination=destination,
            source="manual_publisher_download",
            provenance_extra=provenance,
            registry_payload=provenance,
            relative_paths=(
                Path(record.relative_pdf),
                Path(record.relative_bibtex),
                Path(record.relative_provenance),
            ),
        )

    def acquire_candidate(self, candidate: CandidateMetadata, output: Path) -> dict[str, Any]:
        reference = candidate.official_url or candidate.doi
        if not reference:
            return {
                "status": "deferred",
                "error_code": "invalid_input",
                "message": "candidate has no DOI or official publisher URL",
            }
        try:
            result = self.fetch(reference, output)
        except AccessRequired as exc:
            return {"status": "deferred", "error_code": "access_required", "message": str(exc)}
        except IeeeBridgeError as exc:
            code = (
                "access_required"
                if _is_ieee_access_phase(exc.phase)
                else "contract_error"
            )
            return {"status": "deferred", "error_code": code, "message": str(exc)}
        except RateLimited as exc:
            return {"status": "deferred", "error_code": "rate_limited", "message": str(exc)}
        except NetworkTransient as exc:
            return {
                "status": "deferred",
                "error_code": "network_transient",
                "message": str(exc),
            }
        except (AmbiguousInput, PageContractChanged, MetadataMismatch, BibMissing, InvalidPdfError) as exc:
            return {"status": "deferred", "error_code": "contract_error", "message": str(exc)}
        return {
            "status": "delivered",
            "pdf": str(result.pdf),
            "bibtex": str(result.bibtex),
            "provenance": str(result.provenance),
        }

    def acquire_selected(self, record: SelectionRecord, output: Path) -> dict[str, Any]:
        reference = record.official_url or record.doi
        if not reference:
            return {
                "error_code": "contract_error",
                "message": "selected paper has no DOI or official publisher URL",
            }
        try:
            resolved = self.resolver.resolve(reference)
            pair = resolved.adapter.acquire(resolved.document)
            result = self._deliver_pair(
                pair=pair,
                destination=output,
                source=resolved.adapter.name,
                relative_paths=(
                    Path(record.relative_pdf),
                    Path(record.relative_bibtex),
                    Path(record.relative_provenance),
                ),
                provenance_extra={"selection_id": record.selection_id},
                registry_payload={"selection_id": record.selection_id},
            )
        except AccessRequired as exc:
            return {
                "error_code": "access_required",
                "message": str(exc),
            }
        except IeeeBridgeError as exc:
            code = "access_required" if _is_ieee_access_phase(exc.phase) else "contract_error"
            return {"error_code": code, "message": str(exc)}
        except RateLimited as exc:
            return {"error_code": "rate_limited", "message": str(exc)}
        except NetworkTransient as exc:
            return {"error_code": "network_transient", "message": str(exc)}
        except (AmbiguousInput, PageContractChanged, MetadataMismatch, BibMissing, InvalidPdfError) as exc:
            return {"error_code": "contract_error", "message": str(exc)}
        return {
            "status": "delivered",
            "pdf": str(result.pdf),
            "bibtex": str(result.bibtex),
            "provenance": str(result.provenance),
            "pdf_sha256": sha256_file(result.pdf),
            "bibtex_sha256": sha256_file(result.bibtex),
            "provenance_sha256": sha256_file(result.provenance),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arp")
    parser.add_argument("--version", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    sources = subparsers.add_parser("sources", help="describe offline source capabilities and venue/year gaps")
    sources.add_argument("--spec", type=Path, help="validate and diagnose a corpus specification")
    from acquire_research_papers import configuration_commands, library_cli
    library_cli.register(subparsers)
    schema_command = subparsers.add_parser("schema", help="print a bundled public JSON schema")
    schema_command.add_argument("name")

    for config_command in ("config", "credentials"):
        config = subparsers.add_parser(
            config_command,
            help="show optional capability configuration without revealing secrets",
        )
        config_modes = config.add_subparsers(dest="config_mode", required=True)
        config_status = config_modes.add_parser("status", help="show configured capability booleans")
        config_status.add_argument("--details", action="store_true")
        configuration_commands.register(config_modes)

    fetch = subparsers.add_parser("fetch", help="fetch an official PDF and BibTeX pair")
    fetch.add_argument("--input", required=True)
    fetch.add_argument("--output", type=Path, required=True)
    fetch.add_argument("--ieee-profile", help="use a named institution for this operation")
    fetch.add_argument(
        "--accept-ieee-attribute-release",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="automatically use the configured institutional accept control (enabled by default)",
    )

    manual_fetch = subparsers.add_parser(
        "manual-fetch",
        help="take over after manual publisher PDF and BibTeX downloads",
    )
    manual_fetch.add_argument("--input")
    manual_fetch.add_argument("--selection", type=Path)
    manual_fetch.add_argument("--key")
    manual_fetch.add_argument("--output", type=Path, required=True)
    manual_fetch.add_argument("--watch", type=Path)
    manual_fetch.add_argument("--timeout", type=float, default=900)
    manual_fetch.add_argument("--no-open", action="store_true")
    manual_fetch.add_argument("--pdf", type=Path)
    manual_fetch.add_argument("--bibtex", type=Path)

    export_md = subparsers.add_parser(
        "export-md", help="explicitly parse a PDF with MinerU and export Markdown"
    )
    export_md.add_argument("--pdf", type=Path, required=True)
    export_md.add_argument("--output", type=Path, required=True)

    status = subparsers.add_parser("status", help="show a durable paper state")
    status.add_argument("--paper-id", required=True)

    resume = subparsers.add_parser("resume", help="resume an interrupted acquisition")
    resume.add_argument("--paper-id", required=True)

    review = subparsers.add_parser("review", help="validate semantic review decisions")
    review_modes = review.add_subparsers(dest="review_mode", required=True)
    review_corpus = review_modes.add_parser(
        "corpus", help="import corpus decisions and freeze a selection"
    )
    review_corpus.add_argument("--run", type=Path, required=True)
    review_corpus.add_argument("--decisions", type=Path, required=True)
    review_research = review_modes.add_parser(
        "research", help="freeze explicitly reviewed closest research papers"
    )
    review_research.add_argument("--run", type=Path, required=True)
    review_research.add_argument("--decisions", type=Path, required=True)

    discover = subparsers.add_parser("discover", help="discover a corpus or research evidence")
    discover_modes = discover.add_subparsers(dest="discover_mode", required=True)
    library_cli.register_author(discover_modes)
    corpus = discover_modes.add_parser("corpus", help="plan a quota-driven paper corpus")
    corpus.add_argument("--spec", type=Path, required=True)
    corpus.add_argument("--output", type=Path, required=True)
    corpus.add_argument(
        "--progress",
        action="store_true",
        help="emit sanitized discovery progress as JSON lines on stderr",
    )
    research = discover_modes.add_parser("research", help="plan evidence-driven literature research")
    research.add_argument("--brief", type=Path, required=True)
    research.add_argument("--output", type=Path, required=True)

    acquire = subparsers.add_parser("acquire", help="acquire a frozen corpus selection")
    acquire_modes = acquire.add_subparsers(dest="acquire_mode", required=True)
    acquire_corpus = acquire_modes.add_parser("corpus", help="acquire selected paper pairs")
    acquire_corpus.add_argument("--selection", type=Path, required=True)
    acquire_corpus.add_argument("--output", type=Path, required=True)
    acquire_corpus.add_argument("--ieee-profile")
    acquire_corpus.add_argument(
        "--accept-ieee-attribute-release",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="automatically use the configured institutional accept control (enabled by default)",
    )
    acquire_corpus.add_argument(
        "--defer-host",
        action="append",
        default=[],
        help="defer an exact publisher hostname to the manual-download queue (repeatable)",
    )
    acquire_research = acquire_modes.add_parser(
        "research", help="acquire and parse a frozen closest-paper selection"
    )
    acquire_research.add_argument("--run", type=Path, required=True)
    acquire_research.add_argument("--ieee-profile")
    acquire_research.add_argument(
        "--accept-ieee-attribute-release",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="automatically use the configured institutional accept control (enabled by default)",
    )
    acquire_research.add_argument(
        "--defer-host",
        action="append",
        default=[],
        help="defer an exact publisher hostname to the manual-download queue (repeatable)",
    )

    evidence = subparsers.add_parser(
        "evidence", help="validate claim evidence against hash-bound full text"
    )
    evidence_modes = evidence.add_subparsers(dest="evidence_mode", required=True)
    evidence_research = evidence_modes.add_parser(
        "research", help="import Codex evidence and generate final research reports"
    )
    evidence_research.add_argument("--run", type=Path, required=True)
    evidence_research.add_argument("--records", type=Path, required=True)
    evidence_research.add_argument("--export-csv", action="store_true", help="export papers and claim coverage tables")
    from acquire_research_papers import capability_cli
    capability_cli.register(subparsers, discover_modes=discover_modes, review_modes=review_modes,
                            evidence_modes=evidence_modes, acquire_modes=acquire_modes)
    from acquire_research_papers import host_support
    host_support.register(subparsers)
    def env_option(command):
        command.add_argument("--env-file", type=Path, default=argparse.SUPPRESS,
                             help="select one API dotenv file; no workspace search")
        for action in command._actions:
            if isinstance(action, argparse._SubParsersAction):
                for child in action.choices.values():
                    env_option(child)
    env_option(parser)
    parser.set_defaults(env_file=None)
    return parser


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    application: Application | None = None,
    credential_status: Callable[[], Mapping[str, bool]] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        _emit({"name": "acquire-research-papers", "version": __version__})
        return 0
    from acquire_research_papers import configuration_commands
    from acquire_research_papers import capability_cli
    if args.command == "doctor":
        from acquire_research_papers import host_support
        try:
            result = host_support.dispatch(args)
            _emit(result)
            return 78 if result["status"] == "attention_required" else 0
        except (ValueError, OSError) as exc:
            _emit({"status": "error", "error_code": "configuration_error", "message": str(exc)})
            return 78
    if capability_cli.handles(args):
        try:
            result = capability_cli.dispatch(args, application=application)
            _emit(result)
            return 78 if result.get("status") in {"failed", "configuration_required"} else (
                75 if result.get("status") == "rate_limited" else 0)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            _emit({"status": "error", "error_code": "invalid_input", "message": str(exc)})
            return 64
    if args.command == "sources":
        from acquire_research_papers.source_catalog import describe_sources
        try:
            _emit(describe_sources(load_corpus_spec(args.spec) if args.spec else None))
            return 0
        except (ValueError, OSError, SpecValidationError) as exc:
            _emit({"status": "error", "error_code": "invalid_input", "message": str(exc)})
            return 64
    if args.command == "schema":
        from acquire_research_papers.schema_resources import schema
        try:
            _emit(schema(args.name))
            return 0
        except ValueError as exc:
            _emit({"status": "error", "message": str(exc)})
            return 78
    if args.command in {"config", "credentials"} and args.config_mode != "status":
        try:
            _emit(configuration_commands.dispatch(args))
            return 0
        except (ValueError, OSError, IeeeBridgeError, NetworkTransient,
                MetadataMismatch, BibMissing, InvalidPdfError) as exc:
            phase = getattr(exc, "phase", "configuration")
            retryable = (isinstance(exc, NetworkTransient) or
                         isinstance(exc, configuration_commands.IeeeDiagnosticError) and exc.retryable)
            code = ("network_transient" if retryable else
                    "access_required" if _is_ieee_access_phase(phase) else "configuration_error")
            payload = {"status": "error", "error_code": code, "phase": phase, "message": str(exc)}
            if isinstance(exc, configuration_commands.IeeeDiagnosticError):
                payload["diagnostics"] = exc.diagnostics
            _emit(payload)
            return 75 if code == "network_transient" else 69 if code == "access_required" else 78
    if args.command in {"config", "credentials"} and args.config_mode == "status":
        try:
            paths = configuration_commands.runtime_paths()
            manager = configuration_commands.credential_manager(paths, env_file=args.env_file)
            status = dict(credential_status() if credential_status else manager.status())
            store = configuration_commands.store_for(paths, manager=manager)
            if store.active():
                status["ieee"] = True
            if args.details:
                status["ieee_details"] = store.details()
                status["configuration"] = {"backend": manager.backend,
                    "env_file": str(manager.env_file), "remote_services_verified": False,
                    "api_sources": {key: "environment" if name in manager.environ else manager.backend
                        for key, name in API_KEYS.items()}}
            _emit(status)
            return 0
        except (CredentialStatusError, ValueError, OSError) as exc:
            _emit(
                {
                    "status": "error",
                    "error_code": "contract_error",
                    "message": str(exc),
                }
            )
            return 78
    if args.command == "library" or (args.command == "discover" and args.discover_mode == "author"):
        from acquire_research_papers import library_cli
        try:
            library_app = application
            if (args.command == "library" and args.library_mode == "update"
                    and not args.verify_only and args.watch is None and library_app is None):
                library_app = Application.default(load_discovery_api_keys=False, env_file=args.env_file)
            result = library_cli.dispatch(args, application=library_app)
            _emit(result)
            return 78 if result.get("status") == "failed" else 0
        except (ValueError, OSError, KeyError, TypeError) as exc:
            _emit({"status": "error", "error_code": "invalid_input", "message": str(exc)})
            return 64
    discovery_progress = (
        _stderr_discovery_progress if bool(getattr(args, "progress", False)) else None
    )
    try:
        app = application or Application.default(
            accept_ieee_attribute_release=bool(
                getattr(args, "accept_ieee_attribute_release", True)
            ),
            discovery_progress=discovery_progress,
            load_discovery_api_keys=(args.command == "discover"),
            ieee_profile=getattr(args, "ieee_profile", None),
            env_file=args.env_file,
        )
    except (ApiKeyLoadError, ValueError) as exc:
        _emit(
            {
                "status": "error",
                "error_code": "configuration_error",
                "message": str(exc),
            }
        )
        return 78
    try:
        if args.command == "fetch":
            result = app.fetch(args.input, args.output)
            _emit(
                {
                    "status": result.status,
                    "pdf": str(result.pdf),
                    "bibtex": str(result.bibtex),
                    "provenance": str(result.provenance),
                }
            )
            return 0
        if args.command == "manual-fetch":
            if (args.selection is None) != (args.key is None):
                raise AmbiguousInput(
                    "manual-fetch requires either --input or both --selection and --key"
                )
            single_mode = bool(args.input)
            selection_mode = bool(args.selection and args.key)
            if single_mode == selection_mode:
                raise AmbiguousInput(
                    "manual-fetch requires either --input or both --selection and --key"
                )
            if (args.pdf is None) != (args.bibtex is None):
                raise AmbiguousInput("--pdf and --bibtex must be supplied together")

            def notify(landing_url: str, watch: Path) -> None:
                print(
                    "Download the official PDF and raw BibTeX from "
                    f"{landing_url} into {watch}",
                    file=sys.stderr,
                    flush=True,
                )

            if selection_mode:
                result = app.manual_fetch_selected(
                    args.selection,
                    args.key,
                    args.output,
                    watch=args.watch,
                    timeout_seconds=args.timeout,
                    open_browser=not args.no_open,
                    pdf=args.pdf,
                    bibtex=args.bibtex,
                    notifier=notify,
                )
            else:
                result = app.manual_fetch(
                    args.input,
                    args.output,
                    watch=args.watch,
                    timeout_seconds=args.timeout,
                    open_browser=not args.no_open,
                    pdf=args.pdf,
                    bibtex=args.bibtex,
                    notifier=notify,
                )
            _emit(
                {
                    "status": result.status,
                    "pdf": str(result.pdf),
                    "bibtex": str(result.bibtex),
                    "provenance": str(result.provenance),
                }
            )
            return 0
        if args.command == "export-md":
            result, output, markdown = app.export_markdown(args.pdf, args.output)
            _emit(
                {
                    "status": "exported",
                    "mode": result.mode,
                    "output": str(output),
                    "markdown": str(markdown),
                }
            )
            return 0
        if args.command == "status":
            _emit({"paper_id": args.paper_id, "status": app.registry.status(args.paper_id).value})
            return 0
        if args.command == "discover" and args.discover_mode == "corpus":
            if app.corpus_discovery is None:
                raise AmbiguousInput("corpus discovery is not configured")
            destination = ensure_outside_repository(args.output, app.repository_root)
            result = app.corpus_discovery.run(load_corpus_spec(args.spec), destination)
            _emit(
                {
                    "status": result.status,
                    "candidates": str(result.candidates_path),
                    "evidence_packets": str(result.evidence_path),
                    "pending_metadata": str(result.pending_metadata_path) if result.pending_metadata_path else None,
                    "coverage": str(result.coverage_path),
                    "request": str(result.request_path),
                    "discovery_errors": str(result.diagnostics_path),
                    "manifest": str(result.manifest_path),
                    "reviewable": result.reviewable,
                    "pending_metadata_count": result.pending_metadata,
                    "hard_gate_failed": result.hard_gate_failed,
                    "coverage_incomplete": result.coverage_incomplete,
                }
            )
            return 0
        if args.command == "discover" and args.discover_mode == "research":
            if app.research_workflow is None:
                raise AmbiguousInput("research discovery is not configured")
            try:
                destination = ensure_outside_repository(args.output, app.repository_root)
                result = app.research_workflow.run(
                    load_research_brief(args.brief), destination
                )
            except ValueError as exc:
                raise AmbiguousInput(str(exc)) from exc
            _emit(
                {
                    "status": result.status,
                    "query_passes": result.query_passes,
                    "manifest": str(result.delivery.manifest) if result.delivery.manifest else None,
                    "pending_review": str(result.delivery.pending_review) if result.delivery.pending_review else None,
                    "evidence_map": str(result.delivery.evidence_map) if result.delivery.evidence_map else None,
                    "nearest_work_matrix": str(result.delivery.nearest_work_matrix) if result.delivery.nearest_work_matrix else None,
                    "gap_analysis": str(result.delivery.gap_analysis) if result.delivery.gap_analysis else None,
                    "research_plan": str(result.delivery.research_plan),
                    "candidates": str(result.delivery.candidates_snapshot),
                    "citation_graph": str(result.delivery.citation_graph),
                    "run_manifest": str(result.delivery.run_manifest),
                    "claim_coverage": str(result.delivery.claim_coverage) if result.delivery.claim_coverage else None,
                }
            )
            return 0
        if args.command == "review" and args.review_mode == "corpus":
            try:
                run_root = ensure_outside_repository(args.run, app.repository_root)
                result = CorpusReviewWorkflow().run(run_root, args.decisions)
            except ValueError as exc:
                raise AmbiguousInput(str(exc)) from exc
            _emit(
                {
                    "status": result.status,
                    "reviewed_candidates": str(result.reviewed_path),
                    "pending_review": str(result.pending_review_path),
                    "selected_papers": str(result.selected_path),
                    "selection_manifest": str(result.selection_manifest_path),
                    "manifest": str(result.manifest_path),
                    "accepted": result.accepted,
                    "rejected": result.rejected,
                    "pending": result.pending,
                    "ready_unreviewed": result.ready_unreviewed,
                    "review_completion": result.review_completion,
                    "selected": result.selected,
                    "shortfall_classes": list(result.shortfall_classes),
                    "quota_shortfalls": list(result.quota_shortfalls),
                }
            )
            return 0
        if args.command == "review" and args.review_mode == "research":
            try:
                run_root = ensure_outside_repository(args.run, app.repository_root)
                result = ResearchReviewWorkflow().run(run_root, args.decisions)
            except ValueError as exc:
                raise AmbiguousInput(str(exc)) from exc
            _emit(
                {
                    "status": result.status,
                    "manifest": str(result.manifest_path),
                    "reviewed": str(result.reviewed_path),
                    "pending_review": str(result.pending_path) if result.pending_path else None,
                    "selection_manifest": (
                        str(result.selection_manifest_path)
                        if result.selection_manifest_path
                        else None
                    ),
                    "included": result.included,
                    "excluded": result.excluded,
                    "pending": result.pending,
                }
            )
            return 0
        if args.command == "acquire" and args.acquire_mode == "corpus":
            if app.corpus_acquisition is None:
                raise AmbiguousInput("corpus acquisition is not configured")
            destination = ensure_outside_repository(args.output, app.repository_root)
            try:
                result = app.corpus_acquisition.run(
                    args.selection,
                    destination,
                    deferred_hosts=args.defer_host,
                )
            except ValueError as exc:
                raise AmbiguousInput(str(exc)) from exc
            _emit(
                {
                    "status": result.status,
                    "acquisition_manifest": str(result.acquisition_path),
                    "manual_download": str(result.manual_download_path) if result.manual_download_path else None,
                    "retryable_downloads": str(result.retryable_path) if result.retryable_path else None,
                    "paper_manifest": str(result.paper_manifest_path),
                    "manifest": str(result.manifest_path),
                    "total": result.total,
                    "delivered": result.delivered,
                    "manual_required": result.manual_required,
                    "retryable": result.retryable,
                    "contract_error": result.contract_error,
                    "complete": result.complete,
                }
            )
            return 0
        if args.command == "acquire" and args.acquire_mode == "research":
            if app.research_fulltext is None:
                raise AmbiguousInput("research full-text acquisition is not configured")
            try:
                run_root = ensure_outside_repository(args.run, app.repository_root)
                result = app.research_fulltext.run(
                    run_root,
                    deferred_hosts=args.defer_host,
                )
            except ValueError as exc:
                raise AmbiguousInput(str(exc)) from exc
            _emit(
                {
                    "status": result.status,
                    "full_text_manifest": str(result.full_text_manifest),
                    "manifest": str(result.manifest_path),
                    "acquisition_manifest": str(result.acquisition.manifest_path),
                    "manual_download": str(result.acquisition.manual_download_path) if result.acquisition.manual_download_path else None,
                    "parsed": result.parsed,
                    "pending": result.pending,
                    "acquisition_pending": result.acquisition_pending,
                    "parsing_pending": result.parsing_pending,
                }
            )
            return 0
        if args.command == "evidence" and args.evidence_mode == "research":
            try:
                run_root = ensure_outside_repository(args.run, app.repository_root)
                result = ResearchEvidenceWorkflow().run(run_root, args.records, export_csv=args.export_csv)
            except ValueError as exc:
                raise AmbiguousInput(str(exc)) from exc
            _emit(
                {
                    "status": result.status,
                    "manifest": str(result.manifest_path),
                    "validated_reviews": str(result.reviewed_path),
                    "pending_review": str(result.pending_path) if result.pending_path else None,
                    "evidence_map": str(result.evidence_map) if result.evidence_map else None,
                    "nearest_work_matrix": str(result.nearest_work_matrix) if result.nearest_work_matrix else None,
                    "gap_analysis": str(result.gap_analysis) if result.gap_analysis else None,
                    "claim_coverage": str(result.claim_coverage) if result.claim_coverage else None,
                    "reviewed": result.reviewed,
                    "pending": result.pending,
                    "evidence_records": result.evidence_records,
                    "report": str(result.report) if result.report else None,
                    "papers": str(result.papers) if result.papers else None,
                }
            )
            return 0
        if args.command == "resume":
            raise AmbiguousInput(f"{args.command} requires a task produced by discover")
        parser.print_help()
        return 0
    except (AmbiguousInput, SpecValidationError) as exc:
        _emit({"status": "error", "error_code": "invalid_input", "message": str(exc)})
        return 64
    except AccessRequired as exc:
        _emit({"status": "error", "error_code": "access_required", "message": str(exc)})
        return 69
    except ElsevierApiError as exc:
        if exc.phase == "reference":
            error_code, exit_code = "invalid_input", 64
        elif exc.phase in {"api-key", "entitlement"}:
            error_code, exit_code = "access_required", 69
        else:
            error_code, exit_code = "contract_error", 78
        _emit({"status": "error", "error_code": error_code, "message": str(exc)})
        return exit_code
    except (ManualDownloadTimeout, ManualBrowserOpenError) as exc:
        _emit({"status": "error", "error_code": "manual_handoff_required", "message": str(exc)})
        return 69
    except IeeeBridgeError as exc:
        error_code = (
            "access_required"
            if _is_ieee_access_phase(exc.phase)
            else "contract_error"
        )
        _emit({"status": "error", "error_code": error_code, "message": str(exc)})
        return 69 if error_code == "access_required" else 78
    except (RateLimited, MineruRateLimited) as exc:
        _emit({"status": "error", "error_code": "rate_limited", "message": str(exc)})
        return 75
    except NetworkTransient as exc:
        _emit({"status": "error", "error_code": "network_transient", "message": str(exc)})
        return 75
    except (
        PageContractChanged,
        MetadataMismatch,
        BibMissing,
        InvalidPdfError,
        MineruExtractionError,
        ManualDownloadAmbiguous,
        ManualSourceChanged,
        PdfIdentityMismatch,
        UnicodeError,
        OSError,
    ) as exc:
        _emit({"status": "error", "error_code": "contract_error", "message": str(exc)})
        return 78


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(argv)
