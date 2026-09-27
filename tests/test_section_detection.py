"""Unit tests for deterministic section heading detection."""

from __future__ import annotations

from app.services.pdf_processor import ExtractedPage
from app.services.section_detector import detect_sections


def page(number: int, text: str) -> ExtractedPage:
    return ExtractedPage(page_number=number, text=text)


def test_detects_normal_research_paper_sections() -> None:
    sections = detect_sections(
        [
            page(
                1,
                "Abstract\nSummary of the paper.\n\n"
                "Introduction\nThe research problem.",
            ),
            page(2, "Methods\nThe study design.\n\nResults\nThe findings."),
        ]
    )

    assert [section.section_name for section in sections] == [
        "Abstract",
        "Introduction",
        "Methods",
        "Results",
    ]
    assert sections[0].content == "Summary of the paper."
    assert sections[1].start_page == 1
    assert sections[1].end_page == 1
    assert "The research problem." in sections[1].content


def test_detects_numbered_and_roman_numeral_headings() -> None:
    sections = detect_sections(
        [page(1, "1. Introduction\nIntro body.\n\nIII. METHOD\nMethod body.")]
    )

    assert [section.section_name for section in sections] == [
        "Introduction",
        "Methodology",
    ]


def test_heading_matching_ignores_capitalization_variations() -> None:
    sections = detect_sections(
        [page(1, "aBsTrAcT\nSummary.\n\nCONCLUSION:\nTakeaway.")]
    )

    assert [section.section_name for section in sections] == [
        "Abstract",
        "Conclusion",
    ]


def test_missing_sections_are_not_invented() -> None:
    sections = detect_sections(
        [page(1, "Background\nContext.\n\nFuture Work\nOpen problems.")]
    )

    assert [section.section_name for section in sections] == [
        "Background",
        "Future Work",
    ]


def test_section_content_and_page_range_span_multiple_pages() -> None:
    sections = detect_sections(
        [
            page(1, "Introduction\nOpening paragraph."),
            page(2, "Continuation paragraph."),
            page(3, "Final paragraph.\n\nDiscussion\nInterpretation."),
        ]
    )

    assert sections[0].start_page == 1
    assert sections[0].end_page == 3
    assert "Continuation paragraph." in sections[0].content
    assert "Final paragraph." in sections[0].content
    assert sections[1].start_page == 3


def test_detects_references_and_bibliography_variation() -> None:
    sections = detect_sections(
        [page(1, "Results\nFindings.\n\nReferences\n[1] Citation.")]
    )

    assert sections[-1].section_name == "References"
    assert "[1] Citation." in sections[-1].content


def test_unusual_whitespace_and_headings_wrapped_across_pages() -> None:
    sections = detect_sections(
        [
            page(4, "  2. Materials   and\t\n"),
            page(5, "   Methods  \nStudy details.\n\nREFERENCES\n[1] Source."),
        ]
    )

    assert [section.section_name for section in sections] == [
        "Materials and Methods",
        "References",
    ]
    assert sections[0].start_page == 4
    assert sections[0].end_page == 5


def test_body_prose_is_not_silently_classified_as_a_heading() -> None:
    sections = detect_sections(
        [page(1, "This paper studies methods and results in context.")]
    )

    assert sections == []


def test_no_detectable_sections_returns_an_empty_list() -> None:
    assert detect_sections([page(1, "Unstructured extracted text only.")]) == []


def test_detects_all_documented_heading_families() -> None:
    text = "\n\n".join(
        f"{heading}\nBody for {heading}."
        for heading in (
            "Abstract",
            "Introduction",
            "Related Work",
            "Literature Review",
            "Background",
            "Methodology",
            "Methods",
            "Materials and Methods",
            "Experiments",
            "Results",
            "Discussion",
            "Conclusion",
            "Limitations",
            "Future Work",
            "References",
        )
    )

    assert len(detect_sections([page(1, text)])) == 15
