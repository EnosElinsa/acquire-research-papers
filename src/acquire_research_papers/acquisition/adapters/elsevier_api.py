from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any
from urllib.parse import urlencode, urlsplit

from acquire_research_papers.acquisition.base import SourceDocument
from acquire_research_papers.http import HttpStatusError, RateLimited, SafeHttpClient
from acquire_research_papers.models import PaperMetadata, normalize_doi


ELSEVIER_API_HOST = "api.elsevier.com"
_PII = re.compile(r"^[A-Z0-9]+$")
_DOI = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_SCIENCEDIRECT_PATH = re.compile(r"^/science/article/(?:abs/)?pii/([A-Z0-9]+)/?$")


class ElsevierApiError(RuntimeError):
    def __init__(self, phase: str, message: str) -> None:
        super().__init__(message)
        self.phase = phase


@dataclass(frozen=True)
class ElsevierSearchRecord:
    pii: str
    document: SourceDocument
    metadata_url: str
    author_scope: str = "first_author"


class DpapiElsevierApiKeyProvider:
    def __init__(
        self,
        *,
        script: Path,
        secret_path: Path,
        process_runner: Callable[..., CompletedProcess[str]] = subprocess.run,
        timeout_seconds: int = 30,
    ) -> None:
        self.script = script.resolve()
        self.secret_path = secret_path.resolve()
        self.process_runner = process_runner
        self.timeout_seconds = timeout_seconds

    def __call__(self) -> str:
        try:
            process = self.process_runner(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(self.script),
                    "-ExpectedHost",
                    ELSEVIER_API_HOST,
                    "-SecretPath",
                    str(self.secret_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ElsevierApiError(
                "api-key",
                "Encrypted Elsevier API key could not be loaded.",
            ) from exc
        lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
        if process.returncode != 0 or len(lines) != 1:
            raise ElsevierApiError("api-key", "Encrypted Elsevier API key could not be loaded.")
        return lines[0]


def _raise_search_access_error(error: HttpStatusError) -> None:
    if error.status_code == 401:
        raise ElsevierApiError("api-key", "Elsevier API key was rejected.") from error
    if error.status_code == 403:
        raise ElsevierApiError(
            "entitlement",
            "Elsevier API did not grant access to metadata search.",
        ) from error
    raise ElsevierApiError(
        "api-response",
        f"Elsevier API returned HTTP {error.status_code} for metadata search.",
    ) from error


def _creator_surname(value: str) -> str:
    candidate = value.strip()
    if "," in candidate:
        return candidate.split(",", 1)[0].strip()
    parts = candidate.split()
    while len(parts) > 1 and re.fullmatch(r"(?:[A-Z]\.)+|[A-Z]{1,3}", parts[-1]):
        parts.pop()
    return " ".join(parts)


class ElsevierSearchClient:
    def __init__(self, *, client: SafeHttpClient, key_provider: Callable[[], str]) -> None:
        self.client = client
        self.key_provider = key_provider

    @staticmethod
    def _query(reference: str) -> tuple[str, str | None, str | None]:
        candidate = reference.strip()
        parsed = urlsplit(candidate)
        if parsed.hostname:
            host = parsed.hostname.casefold().rstrip(".")
            if host in {"doi.org", "dx.doi.org"}:
                doi = normalize_doi(parsed.path.lstrip("/"))
                if doi and _DOI.fullmatch(doi):
                    escaped = doi.replace("\\", "\\\\").replace('"', '\\"')
                    return f'DOI("{escaped}")', doi, None
            if host == "www.sciencedirect.com":
                match = _SCIENCEDIRECT_PATH.fullmatch(parsed.path)
                if match:
                    pii = match.group(1).upper()
                    return f"PII({pii})", None, pii
            raise ElsevierApiError("reference", "Reference is not a canonical ScienceDirect URL.")
        doi = normalize_doi(candidate)
        if doi and _DOI.fullmatch(doi):
            escaped = doi.replace("\\", "\\\\").replace('"', '\\"')
            return f'DOI("{escaped}")', doi, None
        raise ElsevierApiError("reference", "Reference must be a DOI or canonical ScienceDirect URL.")

    @staticmethod
    def _entry(payload: dict[str, Any]) -> dict[str, Any]:
        results = payload.get("search-results")
        if not isinstance(results, dict):
            raise ElsevierApiError("metadata", "Elsevier search response is missing results.")
        entries = results.get("entry")
        total_raw = results.get("opensearch:totalResults")
        try:
            total = int(str(total_raw))
        except (TypeError, ValueError) as exc:
            raise ElsevierApiError("metadata", "Elsevier search result count is invalid.") from exc
        if total == 0 or entries in (None, []):
            raise ElsevierApiError("metadata-not-found", "Elsevier search found no matching work.")
        if total != 1 or not isinstance(entries, list) or len(entries) != 1:
            raise ElsevierApiError(
                "metadata-ambiguous",
                "Elsevier search did not return exactly one matching work.",
            )
        entry = entries[0]
        if not isinstance(entry, dict):
            raise ElsevierApiError("metadata", "Elsevier search entry is invalid.")
        return entry

    def resolve(self, reference: str) -> ElsevierSearchRecord:
        query, expected_doi, expected_pii = self._query(reference)
        metadata_url = f"https://{ELSEVIER_API_HOST}/content/search/scopus?" + urlencode(
            {"query": query, "count": 2, "view": "STANDARD"}
        )
        key = self.key_provider()
        if not key.strip():
            raise ElsevierApiError("api-key", "Elsevier API key scope is empty.")
        headers = {"Accept": "application/json", "X-ELS-APIKey": key}
        try:
            try:
                response = self.client.get(metadata_url, headers=headers)
            except RateLimited:
                raise
            except HttpStatusError as exc:
                _raise_search_access_error(exc)
            try:
                payload = response.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise ElsevierApiError("metadata", "Elsevier search returned invalid JSON.") from exc
            if not isinstance(payload, dict):
                raise ElsevierApiError("metadata", "Elsevier search returned invalid metadata.")
            entry = self._entry(payload)
            required = {
                "title": entry.get("dc:title"),
                "creator": entry.get("dc:creator"),
                "venue": entry.get("prism:publicationName"),
                "date": entry.get("prism:coverDate"),
                "doi": entry.get("prism:doi"),
                "pii": entry.get("pii"),
            }
            if not all(isinstance(value, str) and value.strip() for value in required.values()):
                raise ElsevierApiError(
                    "metadata",
                    "Elsevier search result is missing required identity fields.",
                )
            doi = normalize_doi(str(required["doi"]))
            pii = str(required["pii"]).strip().upper()
            date = str(required["date"]).strip()
            creator = _creator_surname(str(required["creator"]))
            if (
                not doi
                or not _DOI.fullmatch(doi)
                or not _PII.fullmatch(pii)
                or not re.match(r"^\d{4}", date)
                or not creator
                or (expected_doi and doi != expected_doi)
                or (expected_pii and pii != expected_pii)
            ):
                raise ElsevierApiError(
                    "metadata",
                    "Elsevier search result does not match the requested work.",
                )
            landing_url = f"https://www.sciencedirect.com/science/article/pii/{pii}"
            document = SourceDocument(
                metadata=PaperMetadata(
                    title=str(required["title"]),
                    authors=(creator,),
                    authors_complete=False,
                    year=int(date[:4]),
                    venue=str(required["venue"]),
                    doi=doi,
                    publisher="Elsevier ScienceDirect",
                    landing_url=landing_url,
                    publication_type=str(entry.get("subtypeDescription") or "Article"),
                ),
                pdf_url=f"{landing_url}/pdfft",
                bibtex_url="https://www.sciencedirect.com/sdfe/arp/cite?"
                + urlencode(
                    {
                        "pii": pii,
                        "format": "text/x-bibtex",
                        "withabstract": "true",
                    }
                ),
                allowed_hosts=frozenset({"www.sciencedirect.com"}),
            )
            return ElsevierSearchRecord(
                pii=pii,
                document=document,
                metadata_url=metadata_url,
            )
        finally:
            key = ""
            headers.clear()
