"""Order keyword-search candidates by how well their title and abstract match the queries.

Search services rank loosely: Crossref's bibliographic search, for example, returned surveys
on proxy re-encryption and music emotion for "mobile robot path planning survey" because
only "survey" matched. A candidate whose title and abstract contain none of a query's topic
words is dropped as noise; the rest are ordered by the share of topic words they contain
(title words count twice), then by how many services found them and by citations. This
nominates candidates for the agent's review; it decides nothing about relevance.
"""
from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from acquire_research_papers.discovery.contracts import CandidateMetadata
from acquire_research_papers.discovery.providers import REVIEW_TITLE_TERMS, title_term_matches

# Words that say what kind of paper is wanted, not what it is about, and function words.
_GENERIC = frozenset({
    "a", "an", "and", "are", "as", "at", "based", "by", "for", "from", "in", "into", "is",
    "its", "of", "on", "or", "the", "their", "to", "toward", "towards", "using", "via",
    "with", "survey", "surveys", "review", "reviews", "overview", "overviews", "tutorial",
    "tutorials", "state", "art", "comprehensive", "systematic", "literature", "recent",
    "advances", "trends", "perspective", "perspectives",
})
_SUFFIXES = ("ations", "ation", "ings", "ing", "ers", "er", "ies", "es", "ed", "s")


def _words(value: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFKC", html.unescape(value)).casefold())


def _stem(word: str) -> str:
    """A prefix that also matches the word's plural and verb forms ("planning" -> "plann")."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def topic_terms(query: str) -> tuple[str, ...]:
    """The stemmed topic words of a query; all its words when it has no topic word."""
    words = _words(query)
    topical = [word for word in words if word not in _GENERIC and len(word) > 1]
    return tuple(dict.fromkeys(_stem(word) for word in (topical or words)))


def _hits(text: str, terms: Sequence[str]) -> set[str]:
    words = " " + " ".join(_words(text)) + " "
    return {term for term in terms if f" {term}" in words}


@dataclass(frozen=True)
class Match:
    score: float
    terms: tuple[str, ...]
    judged: bool  # False when there is no abstract and the title matched nothing


def match(candidate: CandidateMetadata, queries: Iterable[str]) -> Match:
    """The best match of ``candidate`` over ``queries``."""
    best = Match(0.0, (), bool(candidate.abstract.strip()))
    body = " ".join((candidate.abstract, *candidate.keywords))
    for query in queries:
        terms = topic_terms(query)
        if not terms:
            continue
        in_title = _hits(candidate.title, terms)
        in_body = _hits(body, terms)
        score = (2 * len(in_title) + len(in_body)) / (3 * len(terms))
        if score > best.score:
            best = Match(round(score, 3), tuple(sorted(in_title | in_body)), best.judged)
    return best


def _sources(candidate: CandidateMetadata) -> list[str]:
    records = candidate.source_records or (candidate.provenance,)
    return sorted({str(record.get("source")) for record in records
                   if isinstance(record, dict) and record.get("source")})


def rank(candidates: Iterable[CandidateMetadata], queries: Sequence[str], *,
         keep_unmatched: bool = False,
         prefer_named_reviews: bool = False) -> tuple[list[CandidateMetadata], int]:
    """Candidates ordered by match, each with ``provenance.search_match``; and how many were
    dropped because their title and abstract hold none of any query's topic words."""
    kept: list[tuple[tuple[float, ...], CandidateMetadata]] = []
    dropped = 0
    for candidate in candidates:
        found = match(candidate, queries)
        if not found.terms and found.judged and not keep_unmatched:
            dropped += 1
            continue
        sources = _sources(candidate)
        annotated = replace(candidate, provenance={
            **candidate.provenance,
            "search_match": {"score": found.score, "matched_terms": list(found.terms),
                             "sources": sources}})
        # With reviews requested, a title that names a survey outranks a source's type label.
        named_review = prefer_named_reviews and title_term_matches(candidate.title,
                                                                   REVIEW_TITLE_TERMS)
        kept.append(((-int(named_review), -found.score, -len(sources), -candidate.citation_count,
                      -candidate.year), annotated))
    kept.sort(key=lambda item: item[0])  # stable: equal keys keep the merge order
    return [candidate for _, candidate in kept], dropped
