from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from pybtex.database import parse_string

from acquire_research_papers.models import PaperMetadata, normalize_doi


class BibMissing(ValueError):
    """The publisher did not provide a usable BibTeX export."""


class MetadataMismatch(ValueError):
    """Publisher PDF metadata and publisher BibTeX do not identify the same work."""


@dataclass(frozen=True)
class ParsedBibliography:
    key: str
    entry_type: str
    fields: dict[str, str]
    author_surnames: tuple[str, ...]
    raw: str


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+", normalized))


def _surname(value: str) -> str:
    without_aliases = re.sub(r"\([^()]*\)", " ", value)
    normalized = _normalized_text(without_aliases)
    return normalized.split()[-1] if normalized else ""


def _author_key(value: str) -> str:
    without_aliases = re.sub(r"\([^()]*\)", " ", value)
    decomposed = unicodedata.normalize("NFKD", without_aliases).casefold()
    return "".join(
        character
        for character in decomposed
        if character.isalnum() and not unicodedata.combining(character)
    )


def _author_surname_matches(display_name: str, bibtex_surname: str) -> bool:
    display_key = _author_key(display_name)
    surname_key = _author_key(bibtex_surname)
    return bool(display_key and surname_key and display_key.endswith(surname_key))


def _person_surname(person: Any) -> str:
    components = [*person.prelast_names, *person.last_names, *person.lineage_names]
    value = " ".join(str(component) for component in components)
    return _normalized_text(value)


def parse_bibtex(raw: str) -> ParsedBibliography:
    if not raw.strip():
        raise BibMissing("official BibTeX response is empty")
    try:
        bibliography = parse_string(raw, "bibtex")
    except Exception as exc:
        raise MetadataMismatch(f"official BibTeX could not be parsed: {exc}") from exc
    if len(bibliography.entries) != 1:
        raise MetadataMismatch("official BibTeX must contain exactly one entry")
    key, entry = next(iter(bibliography.entries.items()))
    authors = tuple(_person_surname(person) for person in entry.persons.get("author", []))
    return ParsedBibliography(
        key=key,
        entry_type=entry.type,
        fields={name.casefold(): str(value) for name, value in entry.fields.items()},
        author_surnames=authors,
        raw=raw,
    )


_VENUE_EXPANSIONS = {
    "conf": "conference",
    "comput": "computation",
    "evol": "evolutionary",
    "int": "international",
    "intl": "international",
    "proc": "proceedings",
    "trans": "transactions",
}


def _venue_tokens(value: str) -> list[str]:
    ignored = {"of", "the", "proceedings"}
    result = []
    for token in _normalized_text(value).split():
        token = _VENUE_EXPANSIONS.get(token, token)
        if token not in ignored:
            result.append(token)
    return result


def _venue_equivalent(expected: str, actual: str) -> bool:
    expected_tokens = _venue_tokens(expected)
    actual_tokens = _venue_tokens(actual)
    if expected_tokens == actual_tokens:
        return True
    for shorter, longer in ((expected_tokens, actual_tokens), (actual_tokens, expected_tokens)):
        if len(shorter) >= 3 and any(
            longer[index : index + len(shorter)] == shorter
            for index in range(len(longer) - len(shorter) + 1)
        ):
            return True
    return SequenceMatcher(None, " ".join(expected_tokens), " ".join(actual_tokens)).ratio() >= 0.9


def verify_bibliography(metadata: PaperMetadata, parsed: ParsedBibliography) -> None:
    fields = parsed.fields
    actual_doi = normalize_doi(fields.get("doi"))
    if metadata.doi and actual_doi != metadata.doi:
        raise MetadataMismatch(f"DOI mismatch: expected {metadata.doi}, got {actual_doi or 'missing'}")

    actual_year = fields.get("year", "").strip()
    if actual_year != str(metadata.year):
        raise MetadataMismatch(f"year mismatch: expected {metadata.year}, got {actual_year or 'missing'}")

    actual_title = fields.get("title", "")
    title_similarity = SequenceMatcher(
        None, _normalized_text(metadata.title), _normalized_text(actual_title)
    ).ratio()
    if title_similarity < 0.95:
        raise MetadataMismatch(f"title mismatch: similarity {title_similarity:.3f}")

    actual_venue = fields.get("journal") or fields.get("booktitle") or ""
    if metadata.venue and not _venue_equivalent(metadata.venue, actual_venue):
        raise MetadataMismatch(f"venue mismatch: expected {metadata.venue}, got {actual_venue or 'missing'}")

    expected_surnames = tuple(_surname(author) for author in metadata.authors)
    actual_surnames = tuple(parsed.author_surnames)
    if metadata.authors_complete:
        authors_match = len(actual_surnames) == len(metadata.authors) and all(
            _author_surname_matches(author, surname)
            for author, surname in zip(metadata.authors, actual_surnames, strict=True)
        )
    else:
        authors_match = len(actual_surnames) >= len(metadata.authors) and all(
            _author_surname_matches(author, surname)
            for author, surname in zip(metadata.authors, actual_surnames)
        )
    if expected_surnames and not authors_match:
        raise MetadataMismatch(
            f"author mismatch: expected {expected_surnames}, got {actual_surnames or 'missing'}"
        )
