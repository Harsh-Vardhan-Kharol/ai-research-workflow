"""Deterministic evidence matching against persisted page-aware paper text."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import unicodedata
from typing import Any

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EvidenceResult:
    """Verified page passage and traceability state for one extracted claim."""

    page_number: int | None
    section_name: str | None
    source_text: str
    evidence_score: float
    page_corrected: bool
    match_status: str
    failure_code: str | None = None


class MalformedEvidenceSource(ValueError):
    """A stored AI source claim cannot be evaluated as text."""


class EvidenceMapper:
    """Compare an AI source proposal to stored pages; never trust its citation."""

    def __init__(self, min_evidence_threshold: float = 0.35) -> None:
        if not 0 <= min_evidence_threshold <= 1:
            raise ValueError("min_evidence_threshold must be between 0 and 1")
        self.min_evidence_threshold = min_evidence_threshold

    def map_source(
        self,
        source_text: Any,
        proposed_page: Any,
        pages: dict[int, str],
        sections: list[dict[str, Any]],
    ) -> EvidenceResult:
        if source_text is None:
            return _unavailable("missing_source")
        if not isinstance(source_text, str):
            raise MalformedEvidenceSource("source_text must be a string or null")
        query, _ = _normalize_with_map(source_text)
        if not query:
            raise MalformedEvidenceSource("source_text has no searchable characters")
        if not pages:
            return _unavailable("pages_unavailable")

        proposed_valid = (
            isinstance(proposed_page, int)
            and not isinstance(proposed_page, bool)
            and proposed_page in pages
        )
        cited_page_text = pages.get(proposed_page) if proposed_valid else None
        use_fallback = not proposed_valid or not cited_page_text.strip()
        candidate_pages = (
            sorted(pages.items())
            if use_fallback
            else [(proposed_page, cited_page_text)]
        )
        best: tuple[float, int, str] | None = None
        for page_number, page_text in candidate_pages:
            if not page_text:
                continue
            normalized_page, position_map = _normalize_with_map(page_text)
            if not normalized_page:
                continue
            alignment = fuzz.partial_ratio_alignment(query, normalized_page)
            if alignment is None or alignment.dest_end <= alignment.dest_start:
                continue
            start = position_map[alignment.dest_start][0]
            end = position_map[alignment.dest_end - 1][1]
            actual_passage = page_text[start:end].strip()
            score = float(alignment.score) / 100.0
            candidate = (score, page_number, actual_passage)
            if best is None or score > best[0] or (
                score == best[0] and page_number < best[1]
            ):
                best = candidate

        if best is None or best[0] <= 0 or not best[2]:
            return _unavailable(
                "no_match", page_corrected=use_fallback
            )

        score, page_number, actual_passage = best
        match_status = (
            "MATCHED" if score >= self.min_evidence_threshold else "WEAK"
        )
        return EvidenceResult(
            page_number=page_number,
            section_name=_section_for_passage(page_number, actual_passage, sections),
            source_text=actual_passage,
            evidence_score=score,
            page_corrected=use_fallback,
            match_status=match_status,
        )


def _unavailable(
    failure_code: str, page_corrected: bool = False
) -> EvidenceResult:
    return EvidenceResult(
        page_number=None,
        section_name=None,
        source_text="",
        evidence_score=0.0,
        page_corrected=page_corrected,
        match_status="UNAVAILABLE",
        failure_code=failure_code,
    )


def _normalize_with_map(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Casefold, normalize punctuation/spacing, and retain raw character spans."""
    characters: list[str] = []
    spans: list[tuple[int, int]] = []
    for index, character in enumerate(text):
        expanded = unicodedata.normalize("NFKC", character).casefold()
        for item in expanded:
            if item.isalnum():
                characters.append(item)
                spans.append((index, index + 1))
            elif characters and characters[-1] != " ":
                characters.append(" ")
                spans.append((index, index + 1))
    while characters and characters[-1] == " ":
        characters.pop()
        spans.pop()
    normalized = "".join(characters)
    if normalized.startswith(" "):
        normalized = normalized[1:]
        spans = spans[1:]
    return normalized, spans


def _section_for_passage(
    page_number: int, passage: str, sections: list[dict[str, Any]]
) -> str | None:
    normalized_passage, _ = _normalize_with_map(passage)
    candidates = [
        item
        for item in sections
        if item["start_page"] <= page_number <= item["end_page"]
    ]
    for item in candidates:
        section_text, _ = _normalize_with_map(item["content"])
        if normalized_passage and normalized_passage in section_text:
            return item["section_name"]
    return None
