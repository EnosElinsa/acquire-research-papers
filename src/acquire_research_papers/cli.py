from __future__ import annotations

import argparse
import json
import math
import sys
import webbrowser
from collections.abc import Sequence
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
    DpapiElsevierApiKeyProvider,
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
from acquire_research_papers.discovery.contracts import CandidateMetadata
from acquire_research_papers.discovery.coordinator import DiscoveryCoordinator
from acquire_research_papers.discovery.corpus import CorpusDiscoveryWorkflow
from acquire_research_papers.discovery.crossref import CrossrefClient
from acquire_research_papers.discovery.providers import QueryApiProvider
from acquire_research_papers.http import NetworkTransient, RateLimited, SafeHttpClient
from acquire_research_papers.mineru import (
    DpapiMineruTokenProvider,
    MineruCache,
    MineruCliRunner,
    MineruExtractionError,
    MineruRateLimited,
    MineruResult,
)
from acquire_research_papers.models import PaperStatus
from acquire_research_papers.paths import AppPaths, ensure_outside_repository
from acquire_research_papers.registry import Registry
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
        "download-after-auth",
    }
)


def _is_ieee_access_phase(phase: str) -> bool:
    return phase in _IEEE_ACCESS_PHASES


def _resolve_script_root(repository_root: Path, package_root: Path) -> Path:
    for candidate in (repository_root / "scripts", package_root / "_scripts"):
        if all((candidate / name).is_file() for name in _RUNTIME_SCRIPT_NAMES):
            return candidate.resolve()
    raise RuntimeError("acquire-research-papers runtime scripts are missing")


@dataclass
class Application:
    paths: AppPaths
    repository_root: Path
    registry: Registry
    resolver: Resolver
    corpus_discovery: CorpusDiscoveryWorkflow | None = None
    corpus_acquisition: CorpusAcquisitionWorkflow | None = None
    research_workflow: ResearchWorkflow | None = None
    mineru_cache: MineruCache | None = None
    manual_handoff: ManualHandoffWorkflow | None = None
    manual_selection: ManualSelectionWorkflow | None = None

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
            mineru_cache=mineru_cache,
            manual_handoff=manual_handoff,
            manual_selection=manual_selection,
        )
        return application

    @classmethod
    def default(cls) -> Application:
        paths = AppPaths.default()
        paths.create_directories()
        repository_root = Path(__file__).resolve().parents[2]
        script_root = _resolve_script_root(repository_root, Path(__file__).resolve().parent)
        acl = AclAnthologyAdapter(SafeHttpClient(allowed_hosts={"aclanthology.org"}))
        ijcai = IjcaiProceedingsAdapter(SafeHttpClient(allowed_hosts={"www.ijcai.org"}))
        acm = AcmDigitalLibraryAdapter.for_production()
        sciencedirect = ScienceDirectAdapter.for_production()
        ieee = IeeeXploreAdapter(
            IeeeBridge(
                script=script_root / "ieee-playwright.mjs",
                profile_root=paths.profiles / "ieee",
                dependency_root=paths.dependencies,
                work_root=paths.runs,
                secret_path=paths.secrets / "secrets.clixml",
            )
        )
        crossref = CrossrefClient(
            client=SafeHttpClient(allowed_hosts={"api.crossref.org"}),
        )
        mineru_runner = MineruCliRunner(
            token_provider=DpapiMineruTokenProvider(
                script=script_root / "read-mineru-token.ps1",
                secret_path=paths.secrets / "secrets.clixml",
            )
        )
        mineru_cache = MineruCache(paths.cache, runner=mineru_runner)
        elsevier_key = DpapiElsevierApiKeyProvider(
            script=script_root / "read-elsevier-api-key.ps1",
            secret_path=paths.secrets / "secrets.clixml",
        )
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
                discoverer=DiscoveryCoordinator(
                    [QueryApiProvider("crossref", crossref.corpus_searcher)]
                ).discover,
            ),
            corpus_acquisition=None,
            research_workflow=ResearchWorkflow(
                discoverer=ResearchDiscoverer([crossref.corpus_searcher]),
                mineru_cache=mineru_cache,
            ),
            mineru_cache=mineru_cache,
            manual_handoff=manual_handoff,
            manual_selection=ManualSelectionWorkflow(opener=webbrowser.open),
        )
        application.corpus_acquisition = CorpusAcquisitionWorkflow(
            acquirer=application.acquire_selected
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
        reference = candidate.doi or candidate.official_url
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
        reference = record.doi or record.official_url
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

    fetch = subparsers.add_parser("fetch", help="fetch an official PDF and BibTeX pair")
    fetch.add_argument("--input", required=True)
    fetch.add_argument("--output", type=Path, required=True)

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

    review = subparsers.add_parser("review", help="import or inspect review decisions")
    review.add_argument("--input", type=Path, required=True)

    discover = subparsers.add_parser("discover", help="discover a corpus or research evidence")
    discover_modes = discover.add_subparsers(dest="discover_mode", required=True)
    corpus = discover_modes.add_parser("corpus", help="plan a quota-driven paper corpus")
    corpus.add_argument("--spec", type=Path, required=True)
    corpus.add_argument("--output", type=Path, required=True)
    research = discover_modes.add_parser("research", help="plan evidence-driven literature research")
    research.add_argument("--brief", type=Path, required=True)
    research.add_argument("--output", type=Path, required=True)

    acquire = subparsers.add_parser("acquire", help="acquire a frozen corpus selection")
    acquire_modes = acquire.add_subparsers(dest="acquire_mode", required=True)
    acquire_corpus = acquire_modes.add_parser("corpus", help="acquire selected paper pairs")
    acquire_corpus.add_argument("--selection", type=Path, required=True)
    acquire_corpus.add_argument("--output", type=Path, required=True)
    return parser


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    application: Application | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        _emit({"name": "acquire-research-papers", "version": __version__})
        return 0
    app = application or Application.default()
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
                    "selected": str(result.selected_path),
                    "pending_review": str(result.pending_review_path),
                    "discovery_errors": str(result.diagnostics_path),
                    "selection_manifest": str(result.selection_manifest_path),
                    "manifest": str(result.manifest_path),
                    "accepted": result.accepted,
                    "pending": result.pending,
                    "rejected": result.rejected,
                    "not_selected": result.not_selected,
                    "shortfall": result.shortfall,
                    "quota_shortfalls": list(result.quota_shortfalls),
                }
            )
            return 0
        if args.command == "discover" and args.discover_mode == "research":
            if app.research_workflow is None:
                raise AmbiguousInput("research discovery is not configured")
            destination = ensure_outside_repository(args.output, app.repository_root)
            result = app.research_workflow.run(load_research_brief(args.brief), destination)
            _emit(
                {
                    "status": result.status,
                    "query_passes": result.query_passes,
                    "manifest": str(result.delivery.manifest),
                    "pending_review": str(result.delivery.pending_review),
                    "evidence_map": str(result.delivery.evidence_map),
                    "nearest_work_matrix": str(result.delivery.nearest_work_matrix),
                    "gap_analysis": str(result.delivery.gap_analysis),
                    "research_plan": str(result.delivery.research_plan),
                }
            )
            return 0
        if args.command == "acquire" and args.acquire_mode == "corpus":
            if app.corpus_acquisition is None:
                raise AmbiguousInput("corpus acquisition is not configured")
            destination = ensure_outside_repository(args.output, app.repository_root)
            try:
                result = app.corpus_acquisition.run(args.selection, destination)
            except ValueError as exc:
                raise AmbiguousInput(str(exc)) from exc
            _emit(
                {
                    "status": result.status,
                    "acquisition_manifest": str(result.acquisition_path),
                    "manual_download": str(result.manual_download_path),
                    "retryable_downloads": str(result.retryable_path),
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
        if args.command in {"resume", "review"}:
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
