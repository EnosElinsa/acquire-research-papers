"""Read-only adapters for existing run manifests; never rewrite frozen records."""
from __future__ import annotations

import json
from pathlib import Path

from acquire_research_papers.artifacts import sanitize_artifact_value, sha256_file
from acquire_research_papers.run_context import artifact_reference, content_hash
from acquire_research_papers.selection import SelectionStore


MANIFESTS = {
    "discovery-manifest.json": "discovery",
    "review-manifest.json": "review",
    "selection-manifest.json": "selection",
    "research-run.json": "research",
    "delivery-manifest.json": "acquisition",
    "full-text-run.json": "fulltext",
    "research-evidence.json": "evidence",
    "author-discovery.json": "author",
}


def _bound(root: Path, name: str) -> Path:
    target = (root / name).resolve()
    if root not in target.parents:
        raise ValueError("legacy artifact path leaves the run directory")
    return target


def status(root: Path) -> dict:
    root = root.resolve()
    steps, actions = {}, []
    for filename, kind in MANIFESTS.items():
        path = root / filename
        if not path.is_file():
            continue
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError(f"unsupported legacy manifest: {filename}")
        current = value.get("status", "review_required")
        diagnostics = []
        bindings = (("candidates", "candidates_sha256"),
                    ("candidates_file", "candidates_sha256"),
                    ("coverage", "coverage_sha256"),
                    ("evidence_packets", "evidence_packets_sha256"),
                    ("reviewed_candidates", "reviewed_candidates_sha256"),
                    ("full_text_manifest", "full_text_sha256"))
        for field, digest in bindings:
            if field not in value or digest not in value:
                continue
            target = _bound(root, value[field])
            if not target.is_file() or sha256_file(target) != value[digest]:
                current = "stale"
                diagnostics.append({"artifact": field, "reason": "hash_mismatch"})
        try:
            if kind == "selection":
                SelectionStore.load(path)
                current = "frozen"
            elif kind == "research":
                from acquire_research_papers.research.state import read_run_manifest
                read_run_manifest(root)
            elif kind == "author":
                if value.get("sha256") != content_hash({k: v for k, v in value.items() if k != "sha256"}):
                    # Legacy author hashes use default separators rather than canonical JSON.
                    import hashlib
                    expected = hashlib.sha256(json.dumps({k: v for k, v in value.items()
                        if k != "sha256"}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                    if value.get("sha256") != expected:
                        raise ValueError("author snapshot hash mismatch")
                current = "review_required"
            elif kind == "acquisition":
                rows_path = _bound(root, value["acquisition_manifest"])
                rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines()
                        if line.strip()]
                identities = [row.get("selection_id") for row in rows]
                if (len(rows) != value.get("total") or None in identities
                        or len(set(identities)) != len(rows)):
                    raise ValueError("acquisition manifest rows differ from frozen delivery")
                for item_state in ("delivered", "manual_required", "retryable", "contract_error"):
                    if sum(row.get("state") == item_state for row in rows) != value.get(item_state):
                        raise ValueError("acquisition counts changed")
                for row in rows:
                    if row.get("state") != "delivered":
                        continue
                    for artifact in ("pdf", "bibtex", "provenance"):
                        target = Path(row[artifact]).resolve()
                        if root not in target.parents or not target.is_file() or sha256_file(
                                target) != row.get(artifact + "_sha256"):
                            raise ValueError("delivered artifact changed")
        except (ValueError, OSError, KeyError, TypeError):
            current = "stale"
            diagnostics.append({"reason": "legacy_binding_changed"})
        next_actions = []
        if current == "stale":
            next_actions = [{"action": "inspect", "manifest": filename,
                             "reason": "preserve_and_revalidate_changed_artifacts"}]
        elif current not in {"complete", "delivered", "frozen"}:
            action = ("review" if "review" in current or kind == "author" else
                      "manual-fetch" if value.get("manual_required") else "resume")
            next_actions = [{"action": action, "manifest": filename,
                             "status": current, "via": "original-compatible-command"}]
        steps[kind] = {"status": current, "legacy_status": value.get("status"),
                       "artifacts": [artifact_reference(path)],
                       "diagnostics": diagnostics, "next_actions": next_actions}
        actions.extend(next_actions)
    if not steps:
        raise ValueError("no supported run record exists in this directory")
    return sanitize_artifact_value({"schema_version": 1, "run": str(root),
        "compatibility_adapter": True, "steps": steps, "next_actions": actions})
