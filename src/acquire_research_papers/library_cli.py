"""Parser and JSON-result integration for library management and author discovery."""
from __future__ import annotations

from pathlib import Path

from acquire_research_papers.author_discovery import discover_author
from acquire_research_papers.library import (
    apply_plan, audit_library, import_library, organize_library, update_library,
)
from acquire_research_papers.library.metadata import read_json


def register(subparsers) -> None:
    parser = subparsers.add_parser("library", help="audit and plan safe publication-library changes")
    modes = parser.add_subparsers(dest="library_mode", required=True)
    for name in ("audit", "update", "import", "organize"):
        command = modes.add_parser(name)
        command.add_argument("directory", type=Path)
        command.add_argument("--output", type=Path, required=True,
                             help="report directory, or plan.json path for import/organize")
        command.add_argument("--metadata", type=Path, help="offline DOI-to-official-metadata JSON evidence")
        if name == "audit":
            command.add_argument("--export-csv", action="store_true")
        if name == "import":
            command.add_argument("--destination", type=Path, required=True)
            command.add_argument("--chapters", type=Path,
                                 help="explicit chapter identity and 1-based PDF page boundaries JSON")
        if name == "update":
            command.add_argument("--verify-only", action="store_true")
            command.add_argument("--watch", type=Path, help="observe user-downloaded official pairs")
            command.add_argument("--timeout", type=float, default=0, help="bounded watch time, 0–300 seconds")
    apply = modes.add_parser("apply", help="apply or rollback a reviewed hash-bound plan")
    apply.add_argument("plan", type=Path, nargs="?")
    apply.add_argument("--plan", dest="plan_option", type=Path)
    apply.add_argument("--rollback", action="store_true")


def register_author(discover_modes) -> None:
    parser = discover_modes.add_parser("author", help="discover an author's public bibliography with coverage evidence")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--export-csv", action="store_true")
    parser.add_argument("--records", type=Path, help="offline source-to-records JSON evidence")


def dispatch(args, *, application=None) -> dict | None:
    if getattr(args, "command", None) == "discover" and getattr(args, "discover_mode", None) == "author":
        return discover_author(read_json(args.spec),
            records=read_json(args.records) if args.records else None, output=args.output, export_csv=args.export_csv)
    if getattr(args, "command", None) != "library":
        return None
    mode = args.library_mode
    if mode == "apply":
        path = args.plan_option or args.plan
        if path is None or (args.plan_option and args.plan and args.plan_option != args.plan):
            raise ValueError("provide one plan path using --plan or the positional argument")
        return apply_plan(path, rollback=args.rollback)
    metadata = read_json(args.metadata) if args.metadata else None
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("metadata evidence must be a DOI-to-record object")
    if mode == "audit":
        return audit_library(args.directory, metadata=metadata, output=args.output, export_csv=args.export_csv)
    if mode == "update":
        return update_library(args.directory, metadata=metadata, output=args.output,
            application=application, verify_only=args.verify_only, watch=args.watch, timeout=args.timeout)
    if mode == "organize":
        return organize_library(args.directory, metadata=metadata, output=args.output)
    if mode == "import":
        return import_library(args.directory, args.destination, metadata=metadata, output=args.output,
                              chapters=read_json(args.chapters) if args.chapters else None)
    raise ValueError("unsupported library command")
