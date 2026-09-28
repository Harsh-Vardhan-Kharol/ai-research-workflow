"""Deterministic cross-paper comparison over persisted validated extractions."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

from app.database.repository import get_comparison_records
from app.core.config import get_settings
from app.services.normalization import normalize_comparison_value

# Source fields are drawn only from validated extraction groups.
DIMENSIONS: dict[str, tuple[str, ...] | None] = {
    "research_problem_objective": ("research_problem", "research_objective"),
    "methodology_models": ("methodology", "models_algorithms"),
    "datasets": ("datasets",),
    "experimental_setup": ("experimental_setup",),
    "evaluation_metrics": ("evaluation_metrics",),
    "key_results": ("key_results",),
    "limitations": ("limitations",),
    "future_work": ("future_work",),
}
REPEATABLE_DIMENSIONS = {
    "research_problem_objective", "methodology_models", "datasets",
    "evaluation_metrics", "limitations", "future_work",
}


class ComparisonSelectionError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _source(row: Any) -> dict[str, Any]:
    return {
        "extraction_id": row["id"],
        "original_value": row["field_value"],
        "confidence_score": row["confidence_score"],
        "confidence_level": row["confidence_level"],
        "review_required": bool(row["review_required"]),
        "extraction_status": row["status"],
        "review_status": row["review_status"],
        "reviewed_value": row["reviewed_value"],
    }


def compare_papers(connection: Any, paper_ids: list[int]) -> dict[str, Any]:
    """Build frequencies, pairwise differences, coverage, and explicit patterns."""
    if len(paper_ids) < 2:
        raise ComparisonSelectionError(
            "TOO_FEW_PAPERS", "Select at least two papers to compare.", 400
        )
    if len(paper_ids) != len(set(paper_ids)):
        raise ComparisonSelectionError(
            "DUPLICATE_PAPER_IDS", "Paper IDs must be unique.", 422
        )

    papers, rows = get_comparison_records(connection, paper_ids)
    paper_by_id = {row["id"]: row for row in papers}
    missing = [paper_id for paper_id in paper_ids if paper_id not in paper_by_id]
    if missing:
        raise ComparisonSelectionError(
            "PAPER_NOT_FOUND", "One or more selected papers were not found.", 404
        )
    ineligible = [paper_id for paper_id in paper_ids if paper_by_id[paper_id]["status"] != "READY"]
    if ineligible:
        raise ComparisonSelectionError(
            "PAPERS_NOT_READY",
            "One or more selected papers are not ready for comparison.",
            409,
        )

    selected = [
        {"id": paper_id, "title": paper_by_id[paper_id]["title"],
         "file_name": paper_by_id[paper_id]["file_name"], "status": paper_by_id[paper_id]["status"]}
        for paper_id in paper_ids
    ]
    rows_by_paper: dict[int, list[Any]] = defaultdict(list)
    for row in rows:
        rows_by_paper[row["paper_id"]].append(row)

    dimension_results: list[dict[str, Any]] = []
    values_by_dimension: dict[str, dict[int, dict[str, list[dict[str, Any]]]]] = {}
    missing_information = []
    patterns: list[dict[str, Any]] = []
    for dimension, fields in DIMENSIONS.items():
        by_paper: dict[int, dict[str, list[dict[str, Any]]]] = {}
        papers_block = []
        reported_ids: list[int] = []
        for paper_id in paper_ids:
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            if fields is not None:
                for row in rows_by_paper[paper_id]:
                    if row["field_name"] in fields:
                        source = _source(row)
                        grouped[normalize_comparison_value(source["original_value"])].append(source)
            by_paper[paper_id] = dict(grouped)
            reported = bool(grouped)
            if reported:
                reported_ids.append(paper_id)
            papers_block.append({
                "paper_id": paper_id,
                "reported": reported if fields is not None else False,
                "values": [source for sources in grouped.values() for source in sources],
            })
        values_by_dimension[dimension] = by_paper

        frequency_sources: dict[str, list[tuple[int, str, dict[str, Any]]]] = defaultdict(list)
        for paper_id in paper_ids:
            for normalized, sources in by_paper[paper_id].items():
                for source in sources:
                    frequency_sources[normalized].append((paper_id, source["original_value"], source))
        frequencies = []
        for normalized, records in sorted(frequency_sources.items()):
            source_ids = list(dict.fromkeys(record[0] for record in records))
            frequencies.append({
                "normalized_value": normalized,
                "original_values": list(dict.fromkeys(record[1] for record in records)),
                "paper_ids": source_ids,
                "count": len(source_ids),
                "sources": [record[2] for record in records],
            })
        available = fields is not None
        dimension_results.append({
            "name": dimension, "available": available,
            "papers": papers_block, "frequencies": frequencies,
        })
        missing_information.append({
            "dimension": dimension,
            "available": available,
            "reported_by_count": len(reported_ids),
            "selected_paper_count": len(paper_ids),
            "paper_ids_not_reported": (
                [pid for pid in paper_ids if pid not in reported_ids]
                if available else []
            ),
        })
        if dimension in REPEATABLE_DIMENSIONS:
            for frequency in frequencies:
                if frequency["count"] >= 2:
                    original = frequency["original_values"][0]
                    patterns.append({
                        "rule": "repeated_value", "dimension": dimension,
                        "normalized_value": frequency["normalized_value"],
                        "paper_ids": frequency["paper_ids"], "count": frequency["count"],
                        "message": f"Repeated {dimension.replace('_', ' ')}: {original}",
                    })
        if available and len(reported_ids) * 2 < len(paper_ids):
            patterns.append({
                "rule": "sparse_field", "dimension": dimension,
                "normalized_value": None, "paper_ids": reported_ids,
                "count": len(reported_ids),
                "message": f"{dimension.replace('_', ' ').title()} is reported by {len(reported_ids)}/{len(paper_ids)} selected papers.",
            })

    differences = []
    for first_id, second_id in combinations(paper_ids, 2):
        dimension_differences = []
        for dimension, fields in DIMENSIONS.items():
            first_values = set(values_by_dimension[dimension][first_id])
            second_values = set(values_by_dimension[dimension][second_id])
            dimension_differences.append({
                "dimension": dimension,
                "available": fields is not None,
                "shared_values": sorted(first_values & second_values),
                "first_only": sorted(first_values - second_values),
                "second_only": sorted(second_values - first_values),
                "first_reported": bool(first_values),
                "second_reported": bool(second_values),
            })
        differences.append({
            "first_paper_id": first_id, "second_paper_id": second_id,
            "dimensions": dimension_differences,
        })

    method_sets = [set(values_by_dimension["methodology_models"][pid]) for pid in paper_ids]
    method_reporters = [i for i, values in enumerate(method_sets) if values]
    distinct_methods = set().union(*(method_sets[i] for i in method_reporters)) if method_reporters else set()
    if len(method_reporters) >= 2 and len(distinct_methods) >= 2:
        patterns.append({
            "rule": "methodological_variation", "dimension": "methodology_models",
            "normalized_value": None,
            "paper_ids": [paper_ids[i] for i in method_reporters],
            "count": len(distinct_methods),
            "message": "Methodology/model values vary across papers with reported methods.",
        })

    gap_candidates = _gap_candidates(
        paper_ids, values_by_dimension, dimension_results
    )

    return {
        "selected_papers": selected,
        "dimensions": dimension_results,
        "pairwise_differences": differences,
        "missing_information": missing_information,
        "patterns": patterns,
        "limitations": _dimension_summary(
            "limitations", dimension_results, patterns, values_by_dimension
        ),
        "future_work": _dimension_summary(
            "future_work", dimension_results, patterns, values_by_dimension
        ),
        "gap_candidates": gap_candidates,
    }


def _dimension_summary(
    name: str,
    dimensions: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    values_by_dimension: dict[str, dict[int, dict[str, list[dict[str, Any]]]]],
) -> dict[str, Any]:
    dimension = next(item for item in dimensions if item["name"] == name)
    frequencies = []
    for frequency in dimension["frequencies"]:
        sources = [
            dict(source, paper_id=paper_id)
            for paper_id in frequency["paper_ids"]
            for source in values_by_dimension[name][paper_id].get(
                frequency["normalized_value"], []
            )
        ]
        frequencies.append({**frequency, "sources": sources})
    return {
        "available": dimension["available"],
        "frequencies": frequencies,
        "patterns": [p for p in patterns if p["dimension"] == name],
    }


def _gap_candidates(
    paper_ids: list[int],
    values_by_dimension: dict[str, dict[int, dict[str, list[dict[str, Any]]]]],
    dimensions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate scoped, source-traceable candidates from structured values only."""
    settings = get_settings()
    candidates: list[dict[str, Any]] = []
    total = len(paper_ids)

    def add(kind: str, title: str, basis: str, sources: list[dict[str, Any]], values: list[str]) -> None:
        unique_sources = {source["extraction_id"]: source for source in sources}
        ordered = list(unique_sources.values())
        if not ordered:
            return
        ids = list(dict.fromkeys(source["paper_id"] for source in ordered))
        candidates.append({
            "type": kind,
            "title": title,
            "description": f"Potential gap candidate within the selected literature: {title.lower()}.",
            "scope": f"Selected literature ({total} papers)",
            "basis": basis,
            "supporting_paper_ids": ids,
            "supporting_extraction_ids": [source["extraction_id"] for source in ordered],
            "relevant_values": values,
            "sources": ordered,
        })

    for dimension, kind, label in (
        ("datasets", "DATASET_CONCENTRATION", "dataset diversity"),
        ("methodology_models", "METHOD_CONCENTRATION", "methodological diversity"),
    ):
        for frequency in next(d for d in dimensions if d["name"] == dimension)["frequencies"]:
            if frequency["count"] >= 2 and frequency["count"] / total >= settings.gap_concentration_threshold:
                sources = [dict(source, paper_id=pid)
                           for pid in frequency["paper_ids"]
                           for source in values_by_dimension[dimension][pid].get(
                               frequency["normalized_value"], [])]
                value = frequency["original_values"][0]
                add(kind, f"Limited {label}",
                    f"{value} appears in {frequency['count']}/{total} selected papers (threshold: {settings.gap_concentration_threshold:.0%}).",
                    sources, [value])

    for name, kind in (("limitations", "RECURRING_LIMITATION"), ("future_work", "RECURRING_FUTURE_WORK")):
        for frequency in next(d for d in dimensions if d["name"] == name)["frequencies"]:
            if frequency["count"] >= 2:
                paper_for_extraction = _paper_for_sources(values_by_dimension[name], frequency["normalized_value"])
                sources = [dict(source, paper_id=paper_id)
                           for paper_id, source in paper_for_extraction]
                value = frequency["original_values"][0]
                add(kind, f"Recurring {name.replace('_', ' ')}: {value}",
                    f"The same conservatively normalized value occurs in {frequency['count']} selected papers.",
                    sources, frequency["original_values"])

    for dimension in dimensions:
        name = dimension["name"]
        if not dimension["available"]:
            continue
        reported = [paper for paper in dimension["papers"] if paper["reported"]]
        share = len(reported) / total
        if reported and share < settings.gap_sparse_threshold:
            sources = [dict(source, paper_id=paper["paper_id"])
                       for paper in reported for source in paper["values"]]
            add("SPARSE_DIMENSION",
                f"Limited reporting of {name.replace('_', ' ')}",
                f"Structured {name.replace('_', ' ')} values occur in {len(reported)}/{total} selected papers (below {settings.gap_sparse_threshold:.0%}).",
                sources, [name])

    method_map = values_by_dimension["methodology_models"]
    dataset_map = values_by_dimension["datasets"]
    method_keys = sorted(set().union(*(set(method_map[pid]) for pid in paper_ids)))
    dataset_keys = sorted(set().union(*(set(dataset_map[pid]) for pid in paper_ids)))
    for method in method_keys:
        for dataset in dataset_keys:
            co_reporters = [pid for pid in paper_ids if method in method_map[pid] and dataset in dataset_map[pid]]
            if co_reporters:
                continue
            method_sources = [(pid, source) for pid in paper_ids for source in method_map[pid].get(method, [])]
            dataset_sources = [(pid, source) for pid in paper_ids for source in dataset_map[pid].get(dataset, [])]
            sources = [dict(source, paper_id=pid) for pid, source in [*method_sources, *dataset_sources]]
            method_value = method_sources[0][1]["original_value"]
            dataset_value = dataset_sources[0][1]["original_value"]
            add("METHOD_DATASET_ABSENCE",
                f"{method_value} × {dataset_value} coverage is not represented",
                f"Both components are individually reported, but no selected paper's structured record contains both {method_value} and {dataset_value}.",
                sources, [method_value, dataset_value])
    return candidates


def _paper_for_sources(
    values: dict[int, dict[str, list[dict[str, Any]]]], normalized: str
) -> list[tuple[int, dict[str, Any]]]:
    return [(paper_id, source) for paper_id, groups in values.items()
            for source in groups.get(normalized, [])]
