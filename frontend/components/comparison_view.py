"""Pure transformations for rendering traceable comparison tables."""

from __future__ import annotations

from typing import Any


def frequency_rows(dimension: dict[str, Any], papers: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Format one row per normalized value while retaining source metadata."""
    result = []
    for frequency in dimension.get("frequencies", []):
        names = [
            papers.get(paper_id, {}).get("title")
            or papers.get(paper_id, {}).get("file_name")
            or f"Paper #{paper_id}"
            for paper_id in frequency.get("paper_ids", [])
        ]
        result.append({
            "Value": ", ".join(frequency.get("original_values", [])),
            "Papers": ", ".join(names),
            "Count": frequency.get("count", 0),
            "Paper IDs": frequency.get("paper_ids", []),
            "Source records": frequency.get("sources", []),
        })
    return result


def pairwise_rows(comparison: dict[str, Any], papers: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for pair in comparison.get("pairwise_differences", []):
        first = pair["first_paper_id"]
        second = pair["second_paper_id"]
        for dimension in pair.get("dimensions", []):
            if not dimension.get("available", True):
                continue
            if not dimension.get("first_reported") and not dimension.get("second_reported"):
                continue
            first_name = papers.get(first, {}).get("title") or papers.get(first, {}).get("file_name") or f"Paper #{first}"
            second_name = papers.get(second, {}).get("title") or papers.get(second, {}).get("file_name") or f"Paper #{second}"
            result.append({
                "Dimension": dimension["dimension"].replace("_", " ").title(),
                first_name: ", ".join(dimension.get("first_only", [])) or "—",
                second_name: ", ".join(dimension.get("second_only", [])) or "—",
                "Shared": ", ".join(dimension.get("shared_values", [])) or "—",
            })
    return result


def gap_candidate_rows(
    candidates: list[dict[str, Any]], papers: dict[int, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Flatten candidate evidence for display while retaining traceability."""
    papers = papers or {}
    return [{
        "Type": candidate.get("type"),
        "Title": candidate.get("title"),
        "Scope": candidate.get("scope"),
        "Basis": candidate.get("basis"),
        "Paper IDs": candidate.get("supporting_paper_ids", []),
        "Papers": [
            papers.get(paper_id, {}).get("title")
            or papers.get(paper_id, {}).get("file_name")
            or f"Paper #{paper_id}"
            for paper_id in candidate.get("supporting_paper_ids", [])
        ],
        "Extraction IDs": candidate.get("supporting_extraction_ids", []),
        "Sources": candidate.get("sources", []),
    } for candidate in candidates]
