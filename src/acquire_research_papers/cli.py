from __future__ import annotations

import argparse
import json
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
from acquire_research_papers.acquisition.adapters.sciencedirect import ScienceDirectAdapter
from acquire_research_papers.acquisition.adapters.sciencedirect_bridge import ScienceDirectBridge
from acquire_research_papers.acquisition.base import AccessRequired, PageContractChanged, SourceAdapter
from acquire_research_papers.acquisition.router import AdapterRouter
from acquire_research_papers.artifacts import InvalidPdfError, sha256_file
from acquire_research_papers.bibliography import BibMissing, MetadataMismatch
from acquire_research_papers.delivery import DeliveryResult, GenericDelivery
from acquire_research_papers.discovery.corpus import (
    CandidateMetadata,
    CorpusDiscoverer,
    CorpusWorkflow,
)
from acquire_research_papers.discovery.crossref import CrossrefClient
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
from acquire_research_papers.specs import (
    SpecValidationError,
    load_corpus_spec,
    load_research_brief,
)


@dataclass
class Application:
    paths: AppPaths
    repository_root: Path
    registry: Registry
    resolver: Resolver
    corpus_workflow: CorpusWorkflow | None = None
    research_workflow: ResearchWorkflow | None = None
    mineru_cache: MineruCache | None = None

    @classmethod
    def for_test(
        cls,
        *,
        app_root: Path,
        repository_root: Path,
        adapter: SourceAdapter | None = None,
        corpus_workflow: CorpusWorkflow | None = None,
        research_workflow: ResearchWorkflow | None = None,
        mineru_cache: MineruCache | None = None,
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
            corpus_workflow=corpus_workflow,
            research_workflow=research_workflow,
            mineru_cache=mineru_cache,
        )
        return application

    @classmethod
    def default(cls) -> Application:
        paths = AppPaths.default()
        paths.create_directories()
        repository_root = Path(__file__).resolve().parents[2]
        acl = AclAnthologyAdapter(SafeHttpClient(allowed_hosts={"aclanthology.org"}))
        ijcai = IjcaiProceedingsAdapter(SafeHttpClient(allowed_hosts={"www.ijcai.org"}))
        acm = AcmDigitalLibraryAdapter.for_production()
        sciencedirect_bridge = ScienceDirectBridge(
            script=repository_root / "scripts" / "sciencedirect-playwright.mjs",
            profile_root=paths.profiles / "sciencedirect-scau",
            dependency_root=paths.dependencies,
            work_root=paths.runs,
            secret_path=paths.secrets / "secrets.clixml",
        )
        sciencedirect = ScienceDirectAdapter.for_production(bridge=sciencedirect_bridge)
        ieee = IeeeXploreAdapter(
            IeeeBridge(
                script=repository_root / "scripts" / "ieee-playwright.mjs",
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
                script=repository_root / "scripts" / "read-mineru-token.ps1",
                secret_path=paths.secrets / "secrets.clixml",
            )
        )
        mineru_cache = MineruCache(paths.cache, runner=mineru_runner)
        application = cls(
            paths=paths,
            repository_root=repository_root,
            registry=Registry(paths.registry),
            resolver=Resolver(
                AdapterRouter.with_defaults([acl, ijcai, ieee, acm, sciencedirect])
            ),
            corpus_workflow=None,
            research_workflow=ResearchWorkflow(
                discoverer=ResearchDiscoverer([crossref.corpus_searcher]),
                mineru_cache=mineru_cache,
            ),
            mineru_cache=mineru_cache,
        )
        application.corpus_workflow = CorpusWorkflow(
            discoverer=CorpusDiscoverer([crossref.corpus_searcher]),
            acquirer=application.acquire_candidate,
        )
        return application

    def fetch(self, value: str, output: Path) -> DeliveryResult:
        destination = ensure_outside_repository(output, self.repository_root)
        cached = self.registry.verified_delivery(value, destination)
        if cached:
            return DeliveryResult(
                pdf=cached["pdf"],
                bibtex=cached["bibtex"],
                provenance=cached["provenance"],
            )
        resolved = self.resolver.resolve(value)
        metadata = resolved.document.metadata
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

        pair = resolved.adapter.acquire(resolved.document)
        if status is PaperStatus.RESOLVING:
            self.registry.transition(paper_id, PaperStatus.DOWNLOADED)
            status = PaperStatus.DOWNLOADED
        result = GenericDelivery(destination).deliver(pair=pair, paper_id=paper_id)
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
            source=resolved.adapter.name,
            source_url=pair.document.metadata.landing_url,
            payload={
                "pdf": str(result.pdf),
                "bibtex": str(result.bibtex),
                "provenance": str(result.provenance),
            },
        )
        return result

    def export_markdown(self, pdf: Path, output: Path) -> tuple[MineruResult, Path, Path]:
        if self.mineru_cache is None:
            raise MineruExtractionError("MinerU cache is not configured")
        destination = ensure_outside_repository(output, self.repository_root)
        result = self.mineru_cache.parse(pdf.resolve())
        exported = self.mineru_cache.export(result, destination)
        markdown = exported / result.markdown.relative_to(result.output_dir)
        return result, exported, markdown

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
                if exc.phase
                in {"authentication-not-complete", "credential-read", "download-after-auth"}
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arp")
    parser.add_argument("--version", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    fetch = subparsers.add_parser("fetch", help="fetch an official PDF and BibTeX pair")
    fetch.add_argument("--input", required=True)
    fetch.add_argument("--output", type=Path, required=True)

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
            if app.corpus_workflow is None:
                raise AmbiguousInput("corpus discovery is not configured")
            destination = ensure_outside_repository(args.output, app.repository_root)
            result = app.corpus_workflow.run(load_corpus_spec(args.spec), destination)
            _emit(
                {
                    "status": result.status,
                    "candidates": str(result.candidates_path),
                    "pending_review": str(result.pending_review_path),
                    "manifest": str(result.manifest_path),
                    "acquisition_manifest": str(result.acquisition_path),
                    "accepted": result.accepted,
                    "pending": result.pending,
                    "rejected": result.rejected,
                    "delivered": result.delivered,
                    "deferred": result.deferred,
                    "shortfall": result.shortfall,
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
    except IeeeBridgeError as exc:
        error_code = (
            "access_required"
            if exc.phase in {"authentication-not-complete", "credential-read", "download-after-auth"}
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
    ) as exc:
        _emit({"status": "error", "error_code": "contract_error", "message": str(exc)})
        return 78


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(argv)
