"""Deterministic detection of conventional research-paper section headings."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from app.services.pdf_processor import ExtractedPage


@dataclass(frozen=True, slots=True)
class DetectedSection:
    """A detected section and the page range containing its body text."""

    section_name: str
    start_page: int
    end_page: int
    content: str


@dataclass(frozen=True, slots=True)
class _Line:
    page_number: int
    text: str


@dataclass(frozen=True, slots=True)
class _Heading:
    start: int
    end: int
    page_number: int
    section_name: str


_HEADING_NAMES = {
    "abstract": "Abstract",
    "introduction": "Introduction",
    "related work": "Related Work",
    "literature review": "Literature Review",
    "background": "Background",
    "method": "Methodology",
    "methods": "Methods",
    "methodology": "Methodology",
    "materials and methods": "Materials and Methods",
    "proposed method": "Proposed Method",
    "experiment": "Experiments",
    "experiments": "Experiments",
    "results": "Results",
    "discussion": "Discussion",
    "conclusion": "Conclusion",
    "conclusions": "Conclusion",
    "conclusion and future work": "Conclusion and Future Work",
    "threats to validity": "Threats to Validity",
    "study limitations": "Study Limitations",
    "limitations": "Limitations",
    "future work": "Future Work",
    "references": "References",
    "bibliography": "References",
}

_NUMBERING = re.compile(
    r"^(?:(?:\d+(?:\.\d+)*|[IVXLCDM]+|[A-Z])\s*[.)]?\s+)?", re.IGNORECASE
)
_TRAILING_MARKS = re.compile(r"[\s.:;]+$")


def _normalize_heading(text: str) -> str:
    candidate = " ".join(text.split()).strip()
    candidate = _NUMBERING.sub("", candidate)
    candidate = _TRAILING_MARKS.sub("", candidate)
    return " ".join(candidate.casefold().split())


def _lines_from_pages(pages: Sequence[ExtractedPage]) -> list[_Line]:
    lines: list[_Line] = []
    for page in sorted(pages, key=lambda item: item.page_number):
        for line in page.text.splitlines():
            lines.append(_Line(page.page_number, line))
        # Keep page boundaries visible when matching, but allow a heading to
        # wrap from the last line of one page to the first line of the next.
        lines.append(_Line(page.page_number, ""))
    return lines


def _find_headings(lines: Sequence[_Line]) -> list[_Heading]:
    headings: list[_Heading] = []
    index = 0
    while index < len(lines):
        if not lines[index].text.strip():
            index += 1
            continue

        # A heading must occupy a whole extracted line (or a short wrapped
        # heading). Exact known-name matching prevents body prose from matching.
        candidate_lines: list[str] = []
        candidate_indices: list[int] = []
        for stop in range(index, min(index + 3, len(lines))):
            if not lines[stop].text.strip():
                continue
            candidate_lines.append(lines[stop].text.strip())
            candidate_indices.append(stop)
            normalized = _normalize_heading(" ".join(candidate_lines))
            section_name = _HEADING_NAMES.get(normalized)
            if section_name is not None:
                headings.append(
                    _Heading(
                        start=index,
                        end=stop + 1,
                        page_number=lines[index].page_number,
                        section_name=section_name,
                    )
                )
                index = stop + 1
                break
        else:
            index += 1
    return headings


def detect_sections(pages: Sequence[ExtractedPage]) -> list[DetectedSection]:
    """Find known standalone headings and return their page-aware body spans.

    Missing headings are expected. A document with no confidently matched
    standalone heading returns an empty list; callers can retain whole-document
    processing as their fallback.
    """
    lines = _lines_from_pages(pages)
    headings = _find_headings(lines)
    sections: list[DetectedSection] = []

    for position, heading in enumerate(headings):
        next_start = (
            headings[position + 1].start
            if position + 1 < len(headings)
            else len(lines)
        )
        body_lines = lines[heading.end:next_start]
        content = "\n".join(line.text for line in body_lines).strip()
        content_pages = [line.page_number for line in body_lines if line.text.strip()]
        end_page = max(content_pages, default=heading.page_number)
        sections.append(
            DetectedSection(
                section_name=heading.section_name,
                start_page=heading.page_number,
                end_page=max(heading.page_number, end_page),
                content=content,
            )
        )
    return sections
