#!/usr/bin/env python3
"""Run offline evaluation bookkeeping and score optional blind predictions.

Extraction quality is deliberately reported as not measured unless an external
prediction file is supplied. The bundled mock provider is not treated as a
research extraction model.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PAPERS_FILE = ROOT / "data/evaluation/papers.json"
ANNOTATIONS_FILE = ROOT / "data/evaluation/annotations.json"
DEFAULT_OUTPUT = ROOT / "data/evaluation/evaluation_results.json"
EXTRACTION_FIELDS = (
    "title", "authors", "publication_year", "abstract", "research_problem",
    "research_objective", "methodology", "models_algorithms", "datasets",
    "experimental_setup", "evaluation_metrics", "key_results", "limitations",
    "future_work",
)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _partial(left: str, right: str) -> bool:
    a, b = set(normalize(left).split()), set(normalize(right).split())
    return bool(a and b and len(a & b) / len(a | b) >= 0.5)


def score_extractions(papers: dict[str, Any], annotations: dict[str, Any],
                      predictions: dict[str, Any] | None) -> dict[str, Any]:
    if predictions is None:
        return {"status": "Not measured", "reason": "No model predictions supplied; mock-provider output is not treated as extraction performance."}
    counts: Counter[str] = Counter()
    expected_total = predicted_total = exact = normalized_matches = 0
    available_fields = 0
    annotated_empty_fields = 0
    for paper_id in (p["paper_id"] for p in papers["papers"]):
        reference_fields = annotations["papers"].get(paper_id, {})
        prediction_fields = predictions.get("papers", {}).get(paper_id, {})
        for field in EXTRACTION_FIELDS:
            if field not in reference_fields:
                counts["NOT_APPLICABLE"] += 1
                continue
            expected = reference_fields[field]
            if expected is None:
                counts["UNAVAILABLE"] += 1
                continue
            available_fields += 1
            expected = expected or []
            if not expected:
                annotated_empty_fields += 1
            got = prediction_fields.get(field, [])
            expected_total += len(expected)
            predicted_total += len(got)
            unused = set(range(len(got)))
            unmatched = set(range(len(expected)))
            matchers = (
                ("EXACT_MATCH", lambda actual, wanted: actual == wanted),
                ("NORMALIZED_MATCH", lambda actual, wanted: normalize(actual) == normalize(wanted)),
                ("PARTIAL_MATCH", _partial),
            )
            for status, matches in matchers:
                for expected_index in sorted(unmatched):
                    wanted = expected[expected_index]["value"]
                    match = next((i for i in sorted(unused)
                                  if matches(got[i].get("value", ""), wanted)), None)
                    if match is None:
                        continue
                    unmatched.remove(expected_index)
                    unused.remove(match)
                    counts[status] += 1
                    if status == "EXACT_MATCH":
                        exact += 1
                    if status in {"EXACT_MATCH", "NORMALIZED_MATCH"}:
                        normalized_matches += 1
            counts["MISSING"] += len(unmatched)
            counts["INCORRECT"] += len(unused)
    return {
        "status": "measured",
        "matching": "One-to-one greedy item matching: literal equality, then NFKC/casefold/punctuation/whitespace normalization, then Jaccard token overlap >= 0.5 for PARTIAL_MATCH. Only exact and normalized matches count as true positives. Unmatched reference items are MISSING; unmatched predictions are INCORRECT.",
        "item_status_counts": dict(sorted(counts.items())),
        "expected_items": expected_total,
        "annotated_empty_fields": annotated_empty_fields,
        "predicted_items": predicted_total,
        "precision": normalized_matches / predicted_total if predicted_total else None,
        "recall": normalized_matches / expected_total if expected_total else None,
        "f1": (2 * normalized_matches / (predicted_total + expected_total)) if predicted_total + expected_total else None,
        "exact_match_rate": exact / expected_total if expected_total else None,
        "normalized_match_rate": normalized_matches / expected_total if expected_total else None,
        "field_coverage": sum(field in predictions.get("papers", {}).get(pid, {}) for pid, fields in annotations["papers"].items() for field, ref in fields.items() if ref is not None) / available_fields if available_fields else None,
    }


def score_evidence(papers: dict[str, Any], annotations: dict[str, Any],
                   predictions: dict[str, Any] | None) -> dict[str, Any]:
    if predictions is None:
        return {"status": "Not measured", "reason": "No predicted evidence locations supplied."}
    page_text = {p["paper_id"]: p["pages"] for p in papers["papers"]}
    counts: Counter[str] = Counter()
    predicted = correct = expected = 0
    for paper_id, fields in annotations["papers"].items():
        got_fields = predictions.get("papers", {}).get(paper_id, {})
        for field, expected_items in fields.items():
            if expected_items is None:
                counts["UNAVAILABLE"] += 1
                continue
            got = got_fields.get(field, [])
            expected += len(expected_items)
            for index, item in enumerate(got):
                evidence = item.get("evidence")
                if (not evidence or evidence.get("page") is None
                        or not isinstance(evidence.get("quote"), str)
                        or not normalize(evidence.get("quote"))):
                    counts["UNAVAILABLE"] += 1
                    continue
                predicted += 1
                page = evidence["page"]
                quote = evidence["quote"]
                if not isinstance(page, int) or page < 1 or page > len(page_text[paper_id]) or not isinstance(quote, str):
                    counts["INCORRECT_EVIDENCE"] += 1
                elif normalize(quote) in normalize(page_text[paper_id][page - 1]):
                    counts["CORRECT_EVIDENCE"] += 1
                    correct += 1
                elif any(normalize(quote) in normalize(text) for text in page_text[paper_id]):
                    counts["INCORRECT_EVIDENCE"] += 1
                elif _partial(quote, " ".join(page_text[paper_id][page - 1].split())):
                    counts["WEAK"] += 1
                else:
                    counts["INCORRECT_EVIDENCE"] += 1
    return {"status": "measured", "matching": "A predicted quote is correct only when normalized quote text occurs on the predicted 1-based page. A quote found on another page is incorrect; token overlap >= 0.5 on the claimed page is weak. Missing quote/page is unavailable.", "counts": dict(sorted(counts.items())), "predicted_evidence_items": predicted, "expected_evidence_items": expected, "evidence_precision": correct / predicted if predicted else None, "evidence_recall": correct / expected if expected else None}


def _seed_paper(connection: Any, index: int, records: list[tuple[str, str]]) -> tuple[int, dict[str, int]]:
    from app.database.repository import create_paper
    paper_id = create_paper(connection, f"controlled-{index}.pdf", f"{index + 1:064d}")
    connection.execute("UPDATE papers SET status='READY' WHERE id=?", (paper_id,))
    extraction_ids: dict[str, int] = {}
    for item_index, (field, value) in enumerate(records):
        group = "methodology" if field == "methodology" else (
            "experiments" if field in {"datasets", "evaluation_metrics"} else field
        )
        cursor = connection.execute(
            "INSERT INTO extractions (paper_id, group_name, field_name, item_index, field_value, status, section_detected, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'ACCEPTED', 1, 'fixed', 'fixed')",
            (paper_id, group, field, item_index, value),
        )
        extraction_ids[field + ":" + value] = cursor.lastrowid
    return paper_id, extraction_ids


def deterministic_software_metrics() -> dict[str, Any]:
    """Run controlled expected-output checks against current deterministic code."""
    from app.database.connection import connect_database
    from app.database.repository import initialize_schema
    from app.services.comparison_service import compare_papers
    from app.services.confidence import calculate_confidence, route_for_review

    confidence_cases = [
        (1.0, "MATCHED", "HIGH", False), (0.7, "MATCHED", "MEDIUM", False),
        (0.2, "MATCHED", "LOW", True), (1.0, "UNAVAILABLE", "HIGH", True),
        (1.0, "WEAK", "HIGH", True), (0.7, "FAILED", "MEDIUM", True),
    ]
    routing_passed = 0
    for signal, evidence, expected_level, expected_review in confidence_cases:
        result = route_for_review(calculate_confidence({
            "schema_validity": signal, "evidence_strength": signal,
            "source_relevance": signal, "completeness": signal,
        }), evidence)
        routing_passed += result.level == expected_level and result.review_required is expected_review
    if routing_passed != len(confidence_cases):
        raise AssertionError("Controlled confidence routing expectation failed")

    with tempfile.TemporaryDirectory(prefix="researchflow-eval-") as temp_dir:
        connection = connect_database(Path(temp_dir) / "evaluation.db")
        initialize_schema(connection)
        comparison_papers = []
        expected_sources: dict[int, int] = {}
        comparison_rows = [
            [("methodology", "Random Forest"), ("datasets", "Dataset X"), ("evaluation_metrics", "Accuracy")],
            [("methodology", "Random Forest"), ("datasets", "Dataset X"), ("evaluation_metrics", "F1")],
            [("methodology", "XGBoost"), ("datasets", "Dataset Y"), ("evaluation_metrics", "Accuracy")],
        ]
        for index, rows in enumerate(comparison_rows):
            paper_id, ids = _seed_paper(connection, index, rows)
            comparison_papers.append(paper_id)
            expected_sources.update({extraction_id: paper_id for extraction_id in ids.values()})
        connection.commit()
        comparison = compare_papers(connection, comparison_papers)
        expected_counts = {
            ("methodology_models", "random forest"): 2,
            ("methodology_models", "xgboost"): 1,
            ("datasets", "dataset x"): 2, ("datasets", "dataset y"): 1,
            ("evaluation_metrics", "accuracy"): 2, ("evaluation_metrics", "f1"): 1,
        }
        actual = {
            (dimension["name"], frequency["normalized_value"]): frequency["count"]
            for dimension in comparison["dimensions"] for frequency in dimension["frequencies"]
            if dimension["name"] in {"methodology_models", "datasets", "evaluation_metrics"}
        }
        if actual != expected_counts:
            raise AssertionError(f"Comparison fixture mismatch: {actual}")
        observed_sources = {
            source["extraction_id"]: paper["paper_id"]
            for dimension in comparison["dimensions"]
            for paper in dimension["papers"]
            for source in paper["values"]
            if dimension["name"] in {"methodology_models", "datasets", "evaluation_metrics"}
        }
        if observed_sources != expected_sources:
            raise AssertionError("Comparison fixture lost extraction traceability")
        connection.close()

        old_concentration = os.environ.get("GAP_CONCENTRATION_THRESHOLD")
        old_sparse = os.environ.get("GAP_SPARSE_THRESHOLD")
        os.environ["GAP_CONCENTRATION_THRESHOLD"] = "0.70"
        os.environ["GAP_SPARSE_THRESHOLD"] = "0.50"
        try:
            gap_connection = connect_database(Path(temp_dir) / "gaps.db")
            initialize_schema(gap_connection)
            selected = []
            for index in range(8):
                records = []
                if index < 6:
                    records += [("methodology", "Random Forest"), ("datasets", "Dataset X")]
                else:
                    records += [("methodology", "XGBoost"), ("datasets", "Dataset Y")]
                if index == 0:
                    records.append(("evaluation_metrics", "Accuracy"))
                if index in (0, 1):
                    records.append(("limitations", "Small sample size"))
                if index in (1, 2):
                    records.append(("future_work", "Evaluate larger datasets"))
                paper_id, _ = _seed_paper(gap_connection, index + 10, records)
                selected.append(paper_id)
            gap_connection.commit()
            candidates = compare_papers(gap_connection, selected)["gap_candidates"]
            found = {candidate["type"] for candidate in candidates}
            expected_rules = {"DATASET_CONCENTRATION", "METHOD_CONCENTRATION", "SPARSE_DIMENSION", "RECURRING_LIMITATION", "RECURRING_FUTURE_WORK", "METHOD_DATASET_ABSENCE"}
            if not expected_rules.issubset(found):
                raise AssertionError(f"Gap rule fixture mismatch: missing {expected_rules - found}")
            gap_connection.execute(
                "DELETE FROM extractions WHERE paper_id=? AND field_name='datasets' AND field_value='Dataset X'",
                (selected[5],),
            )
            gap_connection.commit()
            below_threshold = compare_papers(gap_connection, selected)["gap_candidates"]
            if any(candidate["type"] == "DATASET_CONCENTRATION" for candidate in below_threshold):
                raise AssertionError("Dataset concentration incorrectly triggered at 5/8")
            gap_connection.close()
        finally:
            if old_concentration is None:
                os.environ.pop("GAP_CONCENTRATION_THRESHOLD", None)
            else:
                os.environ["GAP_CONCENTRATION_THRESHOLD"] = old_concentration
            if old_sparse is None:
                os.environ.pop("GAP_SPARSE_THRESHOLD", None)
            else:
                os.environ["GAP_SPARSE_THRESHOLD"] = old_sparse

    return {
        "confidence_routing": {"status": "measured", "controlled_cases_passed": routing_passed, "controlled_cases": len(confidence_cases), "metric": "Deterministic expected route cases passed; not a probability calibration metric."},
        "comparison": {"status": "measured", "frequency_expectations_passed": len(expected_counts), "frequency_expectations": len(expected_counts), "source_traceability": "passed", "fixture_papers": 3},
        "gap_candidates": {"status": "measured", "supported_rules_found": len(expected_rules), "supported_rules_expected": len(expected_rules), "rules": sorted(expected_rules), "selected_papers": 8, "dataset_concentration_threshold": {"6_of_8": "triggered", "5_of_8": "not_triggered"}},
    }


def run(predictions: dict[str, Any] | None = None) -> dict[str, Any]:
    papers = json.loads(PAPERS_FILE.read_text(encoding="utf-8"))
    annotations = json.loads(ANNOTATIONS_FILE.read_text(encoding="utf-8"))
    paper_count = len(papers["papers"])
    if set(annotations["papers"]) != {p["paper_id"] for p in papers["papers"]}:
        raise ValueError("Paper fixture and annotation IDs do not match")
    deterministic = deterministic_software_metrics()
    controlled_checks = {
        "confidence_routing": {"passed": deterministic["confidence_routing"]["controlled_cases_passed"], "total": deterministic["confidence_routing"]["controlled_cases"]},
        "comparison_frequencies": {"passed": deterministic["comparison"]["frequency_expectations_passed"], "total": deterministic["comparison"]["frequency_expectations"]},
        "gap_rules": {"passed": deterministic["gap_candidates"]["supported_rules_found"], "total": deterministic["gap_candidates"]["supported_rules_expected"]},
        "gap_threshold_boundaries": {"passed": 2, "total": 2},
    }
    return {
        "dataset": {"id": papers["dataset_id"], "paper_count": paper_count,
                    "page_count": sum(len(p["pages"]) for p in papers["papers"]),
                    "source": "synthetic, locally authored fixtures", "annotation_version": annotations["annotation_version"],
                    "annotated_field_count": sum(len(fields) for fields in annotations["papers"].values())},
        "evaluation_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "components": {
            "extraction": score_extractions(papers, annotations, predictions),
            "evidence": score_evidence(papers, annotations, predictions),
            "confidence_routing": deterministic["confidence_routing"],
            "review_workflow": {"status": "covered by deterministic integration tests"},
            "comparison": deterministic["comparison"],
            "gap_candidates": deterministic["gap_candidates"],
            "insight_grounding": {"status": "covered by deterministic mock-provider tests"},
        },
        "controlled_check_counts": controlled_checks,
        "regression_test_suite": {"status": "not run by evaluation runner", "command": "PYTHONPATH=. .venv/bin/python -m pytest -q"},
        "limitations": ["Synthetic dataset of ten compact papers.", "No live or local extraction model benchmark is run by default.", "Manual reference annotations can be subjective.", "Normalization is lexical and does not capture semantic equivalence.", "No significance testing or confidence calibration is attempted."],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, help="Optional JSON predictions keyed by paper ID and extraction field")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    predictions = json.loads(args.predictions.read_text(encoding="utf-8")) if args.predictions else None
    result = run(predictions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
