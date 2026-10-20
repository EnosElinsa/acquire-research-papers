"""Reviewable hash-bound file plans with backups, preflight, resume, and rollback."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from contextlib import contextmanager
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from acquire_research_papers.bibliography import decode_bibtex_bytes, parse_bibtex
from acquire_research_papers.models import normalize_doi
from .audit import scan_library
from .metadata import clean, digest, read_json, write_json


def title_case(value: str) -> str:
    """Capitalize ordinary words while retaining GPU, iPhone, LaTeX, and CJK."""
    def word(match):
        text = match.group()
        if text.isupper() or any(c.isupper() for c in text[1:]):
            return text
        return text[:1].upper() + text[1:]
    return re.sub(r"[^\W\d_]+(?:['’][^\W\d_]+)?", word, value)


def filename_stem(fields: dict, *, path_budget: int = 180) -> str:
    title = title_case(clean(fields.get("title") or "Untitled"))
    venue = fields.get("venue_abbreviation") or fields.get("venue") or "Unknown Venue"
    if len(venue) > 32 and not fields.get("venue_abbreviation"):
        venue = " ".join(word if word.isupper() else word[:1].upper()
                         for word in str(venue).split() if word.casefold() not in {"of", "the", "on", "and"})
    year = str(fields.get("issue_date") or fields.get("year") or fields.get("online_date") or "Unknown")[:4]
    stem = f"{title} - {clean(venue)} - {year}"
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).rstrip(" .")
    stem = re.sub(r"\s+", " ", stem)
    if stem.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                                       *(f"LPT{i}" for i in range(1, 10))}:
        stem = "_" + stem
    if len(stem) > path_budget:
        suffix = hashlib.sha256(stem.encode()).hexdigest()[:10]
        stem = stem[:max(8, path_budget - 13)].rstrip(" .") + " --" + suffix
    return stem


def _plan_digest(plan: dict) -> str:
    body = {key: value for key, value in plan.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def save_plan(actions: list[dict], *, source_root: Path, target_root: Path,
              output: Path, mode: str, diagnostics: list[dict] | None = None) -> dict:
    plan = {"schema_version": 1, "mode": mode, "source_root": str(source_root.resolve()),
            "target_root": str(target_root.resolve()), "actions": actions,
            "diagnostics": diagnostics or []}
    plan["sha256"] = _plan_digest(plan)
    write_json(output, plan)
    return plan


def _destination_stem(fields: dict, root: Path, reserved: set[str], identity: str) -> str:
    budget = min(180, 235 - len(str(root)) - 16)
    if budget < 24:
        raise ValueError("destination directory leaves insufficient filename space")
    stem = filename_stem(fields, path_budget=budget)
    original = stem
    index = 0
    while stem.casefold() in reserved:
        key = hashlib.sha256((identity + str(index)).encode()).hexdigest()[:8]
        stem = original[:budget - 12] + " --" + key
        index += 1
    reserved.add(stem.casefold())
    return stem


def plan_library(directory: Path | str, destination: Path | str, *, output: Path | str,
                 mode: str, metadata: dict | None = None, chapters: list[dict] | None = None) -> dict:
    report = scan_library(directory)
    source_root = Path(report["root"])
    target_root = Path(destination).resolve()
    output = Path(output).resolve()
    if output.suffix.casefold() != ".json":
        raise ValueError("plan output must be a .json file")
    if mode == "import" and (source_root == target_root or source_root in target_root.parents
                             or target_root in source_root.parents):
        raise ValueError("import source and destination directories must not overlap")
    reserved = {p.stem.casefold() for p in target_root.glob("*") if p.is_file()}
    actions, diagnostics = [], []
    for item in report["items"]:
        if item["status"] != "paired":
            diagnostics.append({"source": item.get("bib") or item.get("pdf"),
                                "status": "skipped", "reason": item["status"]})
            continue
        fields = dict(item["local"])
        if metadata and item["doi"] in metadata:
            official = metadata[item["doi"]]
            if normalize_doi(official.get("doi", item["doi"])) != item["doi"]:
                raise ValueError("official metadata DOI mismatch")
            fields.update({k: v for k, v in official.items() if v not in (None, "", [])})
        # The existing pair's stem may be reused for a case-only rename.
        original_stem = Path(item["bib"]).stem
        if mode == "organize" and Path(item["bib"]).parent == target_root:
            reserved.discard(original_stem.casefold())
        stem = _destination_stem(fields, target_root, reserved, item["doi"] + item["bib"])
        for suffix in ("pdf", "bib"):
            source = Path(item[suffix])
            target = target_root / (stem + "." + suffix)
            if str(source) == str(target):
                continue
            actions.append({"operation": "move" if mode == "organize" else "copy",
                "source": str(source), "target": str(target),
                "sha256": item[suffix + "_sha256"], "doi": item["doi"],
                "identity_evidence": item.get("identity_confidence"),
                "citation_source": item.get("citation_source", "manual_import")})
        if item.get("provenance"):
            proof = Path(item["provenance"])
            actions.append({"operation": "move" if mode == "organize" else "copy",
                            "source": str(proof), "target": str(target_root / (stem + ".provenance.json")),
                            "sha256": digest(proof), "doi": item["doi"]})
    if chapters:
        staging = output.parent / ".arp-staging" / (output.stem + "-chapters")
        # Explicit chapter identity and boundaries are mandatory; no automatic TOC inference.
        for index, chapter in enumerate(chapters):
            required = ("source", "doi", "title", "year", "start_page", "end_page")
            if (any(not chapter.get(field) for field in required)
                    or not (chapter.get("bib_file") or chapter.get("bib"))):
                raise ValueError("chapter map requires source, identity, official BibTeX, and page boundaries")
            book = (source_root / chapter["source"]).resolve()
            _contained(book, source_root)
            start, end = int(chapter["start_page"]), int(chapter["end_page"])
            reader = PdfReader(book)
            if not 1 <= start <= end <= len(reader.pages):
                raise ValueError("chapter page boundaries are outside the source PDF")
            citation_file = None
            if chapter.get("bib_file"):
                citation_file = (source_root / chapter["bib_file"]).resolve()
                _contained(citation_file, source_root)
                bib = citation_file.read_bytes()
            else:
                bib = str(chapter["bib"]).encode("utf-8")
            parsed = parse_bibtex(decode_bibtex_bytes(bib)[0])
            if normalize_doi(parsed.fields.get("doi")) != normalize_doi(chapter["doi"]):
                raise ValueError("chapter citation DOI does not match explicit chapter identity")
            def key(value):
                return re.sub(r"\W", "", str(value)).casefold()
            if (key(parsed.fields.get("title")) != key(chapter["title"])
                    or str(parsed.fields.get("year")) != str(chapter["year"])):
                raise ValueError("chapter title/year conflicts with supplied citation")
            staging.mkdir(parents=True, exist_ok=True)
            writer = PdfWriter()
            for page in reader.pages[start - 1:end]:
                writer.add_page(page)
            staged_pdf = staging / f"chapter-{index}.pdf"
            staged_bib = staging / f"chapter-{index}.bib"
            # Never overwrite a previous staged source referenced by a reviewable plan.
            if staged_pdf.exists() or staged_bib.exists():
                raise ValueError("chapter staging already exists; choose a new plan output path")
            with staged_pdf.open("xb") as stream:
                writer.write(stream)
            staged_bib.write_bytes(bib)
            stem = _destination_stem(chapter, target_root, reserved, chapter["doi"])
            provenance = {"kind": "derived_chapter", "source_book": str(book),
                          "source_book_sha256": digest(book), "page_range": [start, end],
                          "chapter_doi": normalize_doi(chapter["doi"]),
                          "bibtex_source": "manual_import" if citation_file else "manual_import_text",
                          "bibtex_sha256": digest(staged_bib), "pdf_sha256": digest(staged_pdf),
                          "metadata": {"doi": normalize_doi(chapter["doi"])}}
            if citation_file:
                provenance.update(citation_source_file=str(citation_file),
                                  citation_source_sha256=digest(citation_file))
            staged_provenance = staging / f"chapter-{index}.provenance.json"
            write_json(staged_provenance, provenance)
            for path in (staged_pdf, staged_bib, staged_provenance):
                suffix = ".provenance.json" if path == staged_provenance else path.suffix
                actions.append({"operation": "copy", "source": str(path),
                    "target": str(target_root / (stem + suffix)), "sha256": digest(path),
                    "doi": normalize_doi(chapter["doi"]), "provenance": provenance})
    return save_plan(actions, source_root=source_root, target_root=target_root,
                     output=output, mode=mode, diagnostics=diagnostics)


def organize_library(directory: Path | str, *, output: Path | str,
                     metadata: dict | None = None) -> dict:
    return plan_library(directory, directory, output=output, mode="organize", metadata=metadata)


def import_library(directory: Path | str, destination: Path | str, *, output: Path | str,
                   metadata: dict | None = None, chapters: list[dict] | None = None) -> dict:
    return plan_library(directory, destination, output=output, mode="import",
                        metadata=metadata, chapters=chapters)


def _contained(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("plan path escapes its declared root") from exc
    current = path
    while True:
        if current.is_symlink():
            raise ValueError("symbolic links are not accepted in file plans")
        if current == current.parent or current == root:
            break
        current = current.parent


def _same_file(first: Path, second: Path) -> bool:
    try:
        return first.samefile(second)
    except OSError:
        return False


def _copy_exclusive(source: Path, target: Path) -> None:
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing)


def _target_spelling_exists(path: Path) -> bool:
    return path.parent.is_dir() and path.name in os.listdir(path.parent)


def _atomic_copy(source: Path, target: Path, temporary: Path, expected: str) -> None:
    if temporary.exists():
        if digest(temporary) != expected:
            temporary.unlink()
    if not temporary.exists():
        _copy_exclusive(source, temporary)
    if digest(temporary) != expected:
        raise ValueError("temporary output hash mismatch")
    # Hard-link a fully written temporary file into a new destination atomically.
    # Unlike replace()/POSIX rename(), this cannot clobber a concurrently created file.
    os.link(temporary, target)
    temporary.unlink()


def _restore(plan: dict, journal: dict, backup_root: Path) -> dict:
    results = []
    for index in reversed(range(len(plan["actions"]))):
        action = plan["actions"][index]
        state = journal["items"].get(str(index))
        if not state or state.get("status") == "rolled_back":
            continue
        source, target = Path(action["source"]), Path(action["target"])
        try:
            if (state.get("status") == "prepared" and action["operation"] == "replace"
                    and target.exists() and digest(target) == action.get("target_sha256")):
                state["status"] = "rolled_back"
                results.append({"index": index, "status": "rolled_back"})
                continue
            source_backup = backup_root / f"{index}.source"
            if not source_backup.is_file() or digest(source_backup) != action["sha256"]:
                raise ValueError("source backup hash mismatch; refusing rollback")
            old_target = backup_root / f"{index}.target"
            if action["operation"] == "replace":
                if not old_target.is_file() or digest(old_target) != action.get("target_sha256"):
                    raise ValueError("original destination backup hash mismatch; refusing rollback")
            if target.exists() and digest(target) != action["sha256"]:
                raise ValueError("destination changed after apply; refusing rollback")
            if action["operation"] == "move":
                if source.exists() and not _same_file(source, target):
                    if digest(source) != action["sha256"]:
                        raise ValueError("source changed after apply; refusing rollback")
                else:
                    if target.exists():
                        target.unlink()
                    source.parent.mkdir(parents=True, exist_ok=True)
                    _copy_exclusive(backup_root / f"{index}.source", source)
            if target.exists() and not _same_file(source, target):
                target.unlink()
            if old_target.exists():
                _copy_exclusive(old_target, target)
            state["status"] = "rolled_back"
            results.append({"index": index, "status": "rolled_back"})
        except Exception as exc:
            results.append({"index": index, "status": "failed", "diagnostic": clean(str(exc))})
    return {"status": "failed" if any(i["status"] == "failed" for i in results) else "rolled_back",
            "items": results}


@contextmanager
def _apply_lock(path: Path):
    """OS-owned locks release on process exit; no stale PID file can block recovery."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("another apply/rollback is using this library") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def apply_plan(path: Path | str, *, rollback: bool = False) -> dict:
    plan = read_json(path)
    if not isinstance(plan, dict) or plan.get("sha256") != _plan_digest(plan):
        raise ValueError("plan digest mismatch; regenerate the plan")
    root = Path(plan["target_root"])
    lock = root / ".arp-backups" / ".apply.lock"
    _contained(lock, root)
    with _apply_lock(lock):
        return _apply_plan(path, rollback=rollback)


def _apply_plan(path: Path | str, *, rollback: bool = False) -> dict:
    plan_path = Path(path).resolve()
    plan = read_json(plan_path)
    if not isinstance(plan, dict) or plan.get("sha256") != _plan_digest(plan):
        raise ValueError("plan digest mismatch; regenerate the plan")
    if plan.get("schema_version") != 1 or not isinstance(plan.get("actions"), list):
        raise ValueError("unsupported library plan")
    root = Path(plan["target_root"])
    source_root = Path(plan["source_root"])
    staging = plan_path.parent / ".arp-staging"
    seen = set()
    for action in plan["actions"]:
        if action.get("operation") not in {"copy", "move", "replace"}:
            raise ValueError("unsupported plan operation")
        source, target = Path(action["source"]), Path(action["target"])
        if not source.is_absolute() or not target.is_absolute():
            raise ValueError("plan paths must be absolute")
        _contained(target, root)
        _contained(source, staging if action.get("provenance") else source_root)
        if str(target).casefold() in seen:
            raise ValueError("plan has colliding destinations")
        seen.add(str(target).casefold())
        provenance = action.get("provenance")
        if provenance:
            book = Path(provenance["source_book"])
            _contained(book, source_root)
            if digest(book) != provenance["source_book_sha256"]:
                raise ValueError("chapter source book hash changed")
            if provenance.get("citation_source_file"):
                original_citation = Path(provenance["citation_source_file"])
                _contained(original_citation, source_root)
                if digest(original_citation) != provenance["citation_source_sha256"]:
                    raise ValueError("chapter source citation hash changed")
    backup_root = root / ".arp-backups" / plan["sha256"][:16]
    _contained(backup_root, root)
    journal_path = backup_root / "journal.json"
    journal = read_json(journal_path) if journal_path.exists() else {"plan": plan["sha256"], "items": {}}
    if journal.get("plan") != plan["sha256"]:
        raise ValueError("backup journal belongs to a different plan")
    if rollback:
        result = _restore(plan, journal, backup_root)
        if journal_path.exists():
            write_json(journal_path, journal)
        return result
    # Preflight all sources and destinations before any mutation.
    failures = []
    for index, action in enumerate(plan["actions"]):
        source, target = Path(action["source"]), Path(action["target"])
        state = journal["items"].get(str(index), {})
        try:
            if state.get("status") in {"applied", "prepared"} and target.exists():
                target_hash = digest(target)
                if target_hash == action["sha256"]:
                    if (state.get("status") == "applied" or not source.exists()
                            or action["operation"] != "move" or _target_spelling_exists(target)):
                        continue
                elif not (state.get("status") == "prepared" and action["operation"] == "replace"
                          and target_hash == action.get("target_sha256")):
                    raise ValueError("applied destination hash changed")
            source_backup = backup_root / f"{index}.source"
            recoverable = (state.get("status") == "prepared" and not source.exists()
                           and source_backup.is_file() and digest(source_backup) == action["sha256"])
            if not recoverable and (not source.is_file() or digest(source) != action["sha256"]):
                raise ValueError("source hash changed or source is missing")
            if target.exists() and not _same_file(source, target):
                if action["operation"] != "replace" or digest(target) != action.get("target_sha256"):
                    raise ValueError("destination already exists; refusing to clobber")
            if target.is_dir():
                raise ValueError("destination is a directory")
        except Exception as exc:
            failures.append({"index": index, "status": "failed", "diagnostic": clean(str(exc))})
    if failures:
        return {"status": "failed", "items": failures, "plan": str(plan_path)}
    backup_root.mkdir(parents=True, exist_ok=True)
    results = []
    for index, action in enumerate(plan["actions"]):
        source, target = Path(action["source"]), Path(action["target"])
        state = journal["items"].get(str(index), {})
        if state.get("status") == "applied":
            results.append({"index": index, "status": "already_applied"})
            continue
        try:
            if (state.get("status") == "prepared" and target.exists()
                    and digest(target) == action["sha256"] and _target_spelling_exists(target)):
                if action["operation"] == "move" and source.exists() and not _same_file(source, target):
                    source.unlink()
                journal["items"][str(index)] = {"status": "applied"}
                write_json(journal_path, journal)
                results.append({"index": index, "status": "resumed"})
                continue
            # Recheck immediately before touching this item, after all-item preflight.
            source_backup = backup_root / f"{index}.source"
            recovery = (state.get("status") == "prepared" and not source.exists()
                        and source_backup.exists() and digest(source_backup) == action["sha256"])
            if not recovery and digest(source) != action["sha256"]:
                raise ValueError("source hash changed during apply")
            if not source_backup.exists():
                _copy_exclusive(source, source_backup)
            if digest(source_backup) != action["sha256"]:
                raise ValueError("source backup hash mismatch")
            same = _same_file(source, target)
            target_backup = backup_root / f"{index}.target"
            if action["operation"] == "replace" and target.exists():
                if digest(target) != action.get("target_sha256"):
                    raise ValueError("replacement destination hash changed")
                if not target_backup.exists():
                    _copy_exclusive(target, target_backup)
            if action["operation"] == "replace" and (not target_backup.exists()
                    or digest(target_backup) != action.get("target_sha256")):
                raise ValueError("original destination backup hash mismatch")
            journal["items"][str(index)] = {"status": "prepared"}
            write_json(journal_path, journal)
            target.parent.mkdir(parents=True, exist_ok=True)
            if same:
                # The backup is the source for a case-only rename; Windows cannot open target exclusively.
                source.unlink()
            elif action["operation"] == "replace" and target.exists():
                target.unlink()
            temporary = target.with_name(target.name + f".arp-{plan['sha256'][:8]}-{index}.tmp")
            _atomic_copy(source_backup, target, temporary, action["sha256"])
            if digest(target) != action["sha256"]:
                raise ValueError("destination hash mismatch")
            if action["operation"] == "move" and source.exists() and not same:
                source.unlink()
            journal["items"][str(index)] = {"status": "applied"}
            write_json(journal_path, journal)
            results.append({"index": index, "status": "applied", "target": str(target)})
        except Exception as exc:
            results.append({"index": index, "status": "failed", "diagnostic": clean(str(exc))})
            restored = _restore(plan, journal, backup_root)
            write_json(journal_path, journal)
            return {"status": "failed", "items": results, "rollback": restored,
                    "backup": str(backup_root), "plan": str(plan_path)}
    return {"status": "applied", "items": results, "backup": str(backup_root), "plan": str(plan_path)}
