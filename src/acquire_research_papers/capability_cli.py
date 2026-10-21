"""Thin capability commands. Offline operations do not construct browser services."""
from __future__ import annotations

import csv
from dataclasses import asdict
import io
import json
from pathlib import Path

from acquire_research_papers.artifacts import atomic_write_bytes, sanitize_artifact_value, sha256_file
from acquire_research_papers.capabilities import (
    OperationResult, compare_collections, freeze_selection, merge_collection,
    metadata_snapshots, resolve_identity, validate_reviews, verify_local_pair,
)
from acquire_research_papers.credentials import ApiKeyLoadError
from acquire_research_papers.contracts import validate_contract
from acquire_research_papers.discovery.contracts import DiscoveryRequest
from acquire_research_papers.mineru import (
    MineruCache, MineruCliRunner, MineruExtractionError, MineruRateLimited,
)
from acquire_research_papers.paths import ensure_outside_repository
from acquire_research_papers.run_context import RunContext, content_hash


def _output_options(command):
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--run", type=Path)


def register(subparsers, *, discover_modes, review_modes, evidence_modes, acquire_modes):
    metadata = subparsers.add_parser("metadata", help="resolve identities or enrich records independently")
    modes = metadata.add_subparsers(dest="metadata_mode", required=True)
    for mode in ("resolve", "enrich"):
        command = modes.add_parser(mode)
        command.add_argument("--input", required=True)
        _output_options(command)
    collection = subparsers.add_parser("collection", help="exact identity merge and set comparison")
    modes = collection.add_subparsers(dest="collection_mode", required=True)
    for mode in ("merge", "compare"):
        command = modes.add_parser(mode)
        command.add_argument("--left", type=Path, required=True)
        command.add_argument("--right", type=Path, required=True)
        _output_options(command)
    verify = subparsers.add_parser("verify", help="verify existing PDF/BibTeX without fetching")
    verify.add_argument("--pdf", type=Path, required=True)
    verify.add_argument("--bibtex", type=Path, required=True)
    verify.add_argument("--expected", type=Path, required=True)
    _output_options(verify)
    parse = subparsers.add_parser("parse", help="parse a local PDF into the internal cache")
    parse.add_argument("--pdf", type=Path, required=True)
    _output_options(parse)
    selection = subparsers.add_parser("selection", help="freeze an explicitly reviewed set")
    modes = selection.add_subparsers(dest="selection_mode", required=True)
    freeze = modes.add_parser("freeze")
    freeze.add_argument("--records", type=Path, required=True)
    freeze.add_argument("--decisions", type=Path, required=True)
    freeze.add_argument("--policy", choices=["identity", "relevance"], default="relevance")
    freeze.add_argument("--maximum", type=int)
    freeze.add_argument("--run", type=Path, required=True)
    review = review_modes.add_parser("import", help="validate identity or relevance decisions")
    review.add_argument("--records", type=Path, required=True)
    review.add_argument("--decisions", type=Path, required=True)
    review.add_argument("--policy", choices=["identity", "relevance"], required=True)
    _output_options(review)
    discover = discover_modes.add_parser("candidates", help="discover without selecting or acquiring")
    discover.add_argument("--query", required=True)
    discover.add_argument("--venue", action="append", default=[])
    discover.add_argument("--year", type=int, action="append", default=[])
    discover.add_argument("--maximum", type=int, default=100)
    _output_options(discover)
    evidence = evidence_modes.add_parser("validate", help="validate excerpts against one exact parse")
    evidence.add_argument("--parse-result", type=Path, required=True)
    evidence.add_argument("--records", type=Path, required=True)
    _output_options(evidence)
    acquire = acquire_modes.add_parser("selection", help="acquire a generic frozen selection")
    acquire.add_argument("--selection", type=Path, required=True)
    acquire.add_argument("--defer-host", action="append", default=[])
    acquire.add_argument("--ieee-profile")
    _output_options(acquire)
    export = subparsers.add_parser("export", help="export records as JSON, CSV or Markdown")
    export.add_argument("--input", type=Path, required=True)
    export.add_argument("--format", choices=["json", "csv", "markdown"], required=True)
    _output_options(export)
    run = subparsers.add_parser("run", help="inspect a lightweight capability run")
    modes = run.add_subparsers(dest="run_mode", required=True)
    status = modes.add_parser("status")
    status.add_argument("--run", type=Path, required=True)


def handles(args) -> bool:
    return (args.command in {"metadata", "collection", "verify", "parse", "selection", "run", "export"}
        or (args.command == "review" and args.review_mode == "import")
        or (args.command == "discover" and args.discover_mode == "candidates")
        or (args.command == "evidence" and args.evidence_mode == "validate")
        or (args.command == "acquire" and args.acquire_mode == "selection"))


def read_value(path: Path):
    try:
        text = path.read_text(encoding="utf-8-sig")
        if path.suffix.casefold() == ".jsonl":
            return [json.loads(line) for line in text.split("\n") if line.strip()]
        return json.loads(text)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError(f"invalid JSON records file: {path}") from None


def read_records(path: Path) -> list[dict]:
    value = read_value(path)
    if isinstance(value, dict):
        value = value.get("records", value.get("papers"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("records input must contain an array of objects or JSON Lines")
    return value


def _write(path: Path, value) -> None:
    atomic_write_bytes(path, (json.dumps(sanitize_artifact_value(value), ensure_ascii=False, indent=2,
                                        sort_keys=True) + "\n").encode("utf-8"))


def request_for(query: str, *, venues=(), years=(), maximum=100) -> DiscoveryRequest:
    if maximum < 1 or any(year < 1000 or year > 9999 for year in years):
        raise ValueError("maximum must be positive and years must have four digits")
    return DiscoveryRequest.from_spec({"name": query, "target": {"minimum": 0, "maximum": maximum},
        "scope": {"venues": [{"name": v} for v in venues], "years": {"include": list(years)},
                  "topics": {"include": [query]}}})


def validate_fulltext(parse_result: dict, decisions: list[dict]) -> dict:
    from acquire_research_papers.review_contracts import review_metadata
    from acquire_research_papers.research.evidence import EvidenceRecord
    for kind, key in (("pdf", "full_text_sha256"), ("markdown", "markdown_sha256")):
        if sha256_file(Path(parse_result[kind])) != parse_result[key]:
            raise ValueError("full-text artifact hash mismatch")
    markdown = " ".join(Path(parse_result["markdown"]).read_text(encoding="utf-8").split())
    records = []
    for decision in decisions:
        validate_contract(decision, "capability-evidence-review.schema.json")
        review_metadata(decision)
        if any(decision.get(key) != parse_result[key]
               for key in ("full_text_sha256", "markdown_sha256")):
            raise ValueError("evidence review hash mismatch")
        for item in decision.get("records", []):
            record = EvidenceRecord(**item).validate()
            if record.paper_id != parse_result.get("paper_id", "sha256:" + parse_result["full_text_sha256"]):
                raise ValueError("evidence paper_id does not match the exact parsed document")
            if record.read_scope != "full-text" or not record.excerpt.strip() or " ".join(
                    record.excerpt.split()) not in markdown:
                raise ValueError("evidence excerpt is absent from the exact full text")
            records.append(record.to_dict())
    claims = sorted({r["claim_id"] for r in records})
    coverage = [{"claim_id": claim, "evidence_count": sum(r["claim_id"] == claim for r in records),
                 "paper_id": parse_result.get("paper_id", "sha256:" + parse_result["full_text_sha256"]),
                 "full_text_sha256": parse_result["full_text_sha256"],
                 "read_scope": "full-text"} for claim in claims]
    return {"records": records, "coverage": coverage, "reviews": decisions,
            "completed": len(decisions), "pending": 0,
            "source_trust": parse_result.get("source_trust", "user-supplied")}


def _export(records: list[dict], format: str) -> bytes:
    if format == "json":
        return (json.dumps(records, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    columns = sorted({key for record in records for key in record})
    def cell(value):
        return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else (
            "" if value is None else str(value))
    if format == "csv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows([[cell(row.get(key)) for key in columns] for row in records])
        return stream.getvalue().encode("utf-8-sig")
    def row(values):
        return "| " + " | ".join(cell(v).replace("|", "\\|").replace("\n", "<br>")
                                  for v in values) + " |\n"
    return (row(columns) + row(["---"] * len(columns))
            + "".join(row([r.get(k) for k in columns]) for r in records)).encode("utf-8")


def dispatch(args, *, application=None) -> dict:
    from acquire_research_papers import configuration_commands as config
    from acquire_research_papers.cli import Application
    paths = application.paths if application else config.runtime_paths()
    repository = application.repository_root if application else Path(__file__).resolve().parents[2]
    if args.command == "run":
        if not (args.run / "run-context.json").exists():
            from acquire_research_papers.legacy_runs import status
            return status(args.run)
        return RunContext(args.run).status()
    output = getattr(args, "output", None)
    if output:
        output = ensure_outside_repository(output, repository)
    run = ensure_outside_repository(args.run, repository) if args.run else None
    inputs = [value for name, value in vars(args).items() if isinstance(value, Path)
              and name not in {"run", "output", "env_file"}]
    if args.command == "metadata" and args.metadata_mode == "enrich":
        inputs.append(Path(args.input))
    identity_record = None
    if (args.command == "metadata" and args.metadata_mode == "resolve"
            and not args.input.startswith(("http://", "https://", "10."))):
        record_path = Path(args.input)
        if record_path.is_file():
            identity_record = read_value(record_path)
            if not isinstance(identity_record, dict):
                raise ValueError("identity JSON input must contain one candidate object")
            inputs.append(record_path)
    if args.command == "acquire":
        from acquire_research_papers.selection import SelectionStore
        # Validate frozen contents even when a prior successful step is reusable.
        selection = SelectionStore.load(args.selection)
        inputs.append(selection.selected_path)
    parameters = {name: str(value) if isinstance(value, Path) else value
                  for name, value in vars(args).items() if name != "env_file"}

    def app():
        return application or Application.default(env_file=args.env_file,
            load_discovery_api_keys=True, ieee_profile=getattr(args, "ieee_profile", None))

    def operation():
        payload = {}
        if args.command == "metadata":
            if args.metadata_mode == "resolve":
                payload = resolve_identity(identity_record if identity_record is not None else args.input)
            else:
                service = app().discovery_coordinator
                if service is None:
                    raise ValueError("metadata service is not configured")
                payload = metadata_snapshots(read_records(Path(args.input)), coordinator=service,
                                             request=request_for("metadata enrichment"))
        elif args.command == "collection":
            left, right = read_records(args.left), read_records(args.right)
            payload = (compare_collections(left, right) if args.collection_mode == "compare"
                       else merge_collection([*left, *right]))
        elif args.command == "verify":
            payload = verify_local_pair(args.pdf, args.bibtex, read_value(args.expected))
        elif args.command == "parse":
            cache = application.mineru_cache if application else MineruCache(paths.cache,
                runner=MineruCliRunner(token_provider=config.credential_manager(paths,
                    env_file=args.env_file).api_provider("mineru", "mineru.net")))
            if cache is None:
                raise ValueError("parser cache is not configured")
            parsed = cache.parse(args.pdf.resolve())
            payload = {"pdf": str(args.pdf.resolve()), "markdown": str(parsed.markdown),
                       "paper_id": "sha256:" + sha256_file(args.pdf),
                       "full_text_sha256": sha256_file(args.pdf),
                       "markdown_sha256": sha256_file(parsed.markdown), "mode": parsed.mode,
                       "source_trust": "user-supplied", "official_acquisition_complete": False,
                       "outputs": [str(parsed.markdown)]}
        elif args.command == "selection":
            return freeze_selection(read_records(args.records), read_records(args.decisions), run,
                                    policy=args.policy, maximum=args.maximum)
        elif args.command == "review":
            rows = validate_reviews(read_records(args.records), read_records(args.decisions), policy=args.policy)
            reviewed = {r["identity"] for r in rows if r["decision"] != "pending"}
            outstanding = sorted({resolve_identity(r)["identity"] for r in read_records(args.records)
                                  if resolve_identity(r)["identity"]} - reviewed)
            payload = {"records": rows, "completed": len(reviewed), "pending": len(outstanding),
                       "status": "review_required" if outstanding else "complete",
                       "next_actions": [{"action": "review", "identity": key,
                                         "policy": args.policy} for key in outstanding]}
        elif args.command == "discover":
            coordinator = app().discovery_coordinator
            if coordinator is None:
                raise ValueError("discovery service is not configured")
            batch = coordinator.discover(request_for(args.query, venues=args.venue,
                                          years=args.year, maximum=args.maximum))
            payload = {"records": [r.to_dict() for r in batch.candidates],
                "coverage": [asdict(r) for r in batch.coverage],
                "diagnostics": [asdict(r) for r in batch.diagnostics],
                "completed": len(batch.candidates)}
            if batch.diagnostics or any(r.state != "complete" for r in batch.coverage):
                payload.update(status="partial", next_actions=[{"action": "resume",
                    "provider": r.provider_id, "reason": r.error_code} for r in batch.diagnostics])
        elif args.command == "evidence":
            parse_result = read_value(args.parse_result)
            payload = validate_fulltext(parse_result, read_records(args.records))
        elif args.command == "acquire":
            result = app().corpus_acquisition.run(args.selection, output,
                                                  deferred_hosts=args.defer_host)
            rows = read_records(result.acquisition_path)
            states = {"delivered": "complete", "manual_required": "user_download",
                      "retryable": "retryable", "contract_error": "failed"}
            items = {r["selection_id"]: {"status": "rate_limited" if r.get("error_code") == "rate_limited"
                     else states[r["state"]]} for r in rows}
            artifacts = [result.acquisition_path, result.manual_download_path,
                         result.retryable_path, result.paper_manifest_path, result.manifest_path]
            artifacts.extend(Path(r[k]) for r in rows if r["state"] == "delivered"
                             for k in ("pdf", "bibtex", "provenance"))
            return {"status": "complete" if result.status == "delivered" else (
                        "failed" if result.contract_error and not result.manual_required
                        and not result.retryable else "pending"),
                    "completed": result.delivered, "pending": len(rows) - result.delivered,
                    "items": items, "outputs": [str(p) for p in artifacts if p is not None],
                    "next_actions": [{"action": "manual-fetch" if item["status"] == "user_download"
                        else "inspect-source" if item["status"] == "failed" else "resume",
                        "item": key} for key, item in items.items() if item["status"] != "complete"]}
        elif args.command == "export":
            atomic_write_bytes(output, _export(sanitize_artifact_value(read_records(args.input)), args.format))
            return OperationResult(completed=1, outputs=(str(output),)).to_dict()
        payload = {**OperationResult(completed=1).to_dict(), **payload}
        if payload.get("status") in {"resolved", "unresolved", "ambiguous"}:
            payload["identity_status"] = payload.pop("status")
            payload["status"] = "complete"
        payload = sanitize_artifact_value(payload)
        validate_contract(payload, "operation-result.schema.json")
        _write(output, payload)
        payload["outputs"] = [*payload.get("outputs", []), str(output)]
        return payload

    def guarded():
        try:
            return operation()
        except ApiKeyLoadError:
            return {"status": "configuration_required", "completed": 0,
                    "next_actions": [{"action": "config setup", "provider": "mineru" if args.command == "parse" else "required-provider"}]}
        except MineruRateLimited:
            return {"status": "rate_limited", "completed": 0,
                    "next_actions": [{"action": "resume", "reason": "rate_limited"}]}
        except MineruExtractionError:
            return {"status": "failed", "completed": 0,
                    "next_actions": [{"action": "doctor", "reason": "parser_failed"}]}
    if run:
        if args.command == "evidence":
            parse_result = read_value(args.parse_result)
            inputs.extend([Path(parse_result["pdf"]), Path(parse_result["markdown"])])
        mode = next((str(v) for k, v in vars(args).items() if k.endswith("_mode")), "default")
        step = args.command + ":" + mode + ":" + content_hash(parameters)[:12]
        return RunContext(run).execute(step, inputs=inputs, parameters=parameters, operation=guarded)
    return guarded()
