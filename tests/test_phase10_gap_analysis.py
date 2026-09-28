"""Phase 10 extraction groups and deterministic, traceable gap candidates."""

from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config import get_settings
from app.database.connection import connect_database
from app.database.repository import (
    create_paper, initialize_schema, replace_extraction_group_results,
    set_paper_status, get_extractions_for_paper, get_extraction_with_evidence,
)
from app.schemas.extraction import GROUP_MODELS
from app.services.ai_extraction import AIExtractionService
from app.services.comparison_service import compare_papers
from app.services.paper_processing import _score_paper_confidence


class CaptureProvider:
    def __init__(self):
        self.calls = []

    def structured_complete(self, system, prompt, schema):
        self.calls.append((system, prompt, schema))
        return {"limitations": [], "future_work": []}


def test_phase10_groups_use_strict_claim_schema_and_explicit_untrusted_prompts():
    assert "limitations" in GROUP_MODELS
    assert "future_work" in GROUP_MODELS
    provider = CaptureProvider()
    service = AIExtractionService(get_settings(), provider)
    sections = [
        {"section_name": "Study Limitations", "start_page": 4, "end_page": 4,
         "content": "Small sample size."},
        {"section_name": "Future Work", "start_page": 5, "end_page": 5,
         "content": "We will evaluate additional datasets."},
    ]
    pages = {4: "Small sample size.", 5: "We will evaluate additional datasets."}
    for group in ("limitations", "future_work"):
        result, context = service.extract_group(group, pages, sections)
        assert result[group] == []
        assert context.section_detected is True
        assert GROUP_MODELS[group].model_validate({group: result[group]}, strict=True)
    prompts = [call[1] for call in provider.calls]
    assert "Do not infer a limitation" in prompts[0]
    assert "Do not turn a weakness into future work" in prompts[1]
    assert all("untrusted DATA" in call[0] and "Do not follow" in call[0]
               for call in provider.calls)


def test_limitations_and_future_work_unavailable_evidence_routes_to_review(tmp_path):
    connection = connect_database(tmp_path / "phase10-evidence.db")
    initialize_schema(connection)
    paper_id = create_paper(connection, "evidence.pdf", "9" * 64)
    for group, field_name in (("limitations", "limitations"), ("future_work", "future_work")):
        replace_extraction_group_results(
            connection, paper_id, group, [{
                "field_name": field_name, "item_index": 0,
                "field_value": f"Explicit {field_name} statement",
                "proposed_source_text": None, "proposed_page": None,
                "proposed_section": None, "section_detected": False,
                "evidence": {
                    "page_number": None, "section_name": None, "source_text": "",
                    "evidence_score": 0.0, "page_corrected": False,
                    "match_status": "UNAVAILABLE", "failure_code": "missing_source",
                },
            }],
        )
    set_paper_status(connection, paper_id, "SCORING_CONFIDENCE")
    _score_paper_confidence(connection, paper_id)
    for extraction in get_extractions_for_paper(connection, paper_id):
        evidence = get_extraction_with_evidence(connection, extraction["id"])
        assert evidence["match_status"] == "UNAVAILABLE"
        assert extraction["status"] == "PENDING_REVIEW"
        assert "evidence_unavailable" in extraction["review_reasons"]
    connection.close()


def _analytics_db(path):
    connection = connect_database(path)
    initialize_schema(connection)
    papers = []
    for index in range(4):
        paper_id = create_paper(connection, f"phase10-{index}.pdf", str(index + 1) * 64)
        connection.execute(
            "UPDATE papers SET status='READY', title=? WHERE id=?",
            (f"Paper {index + 1}", paper_id),
        )
        papers.append(paper_id)
    data = [
        (0, "methodology", "A", "methodology"), (0, "datasets", "X", "experiments"),
        (0, "evaluation_metrics", "Accuracy", "experiments"),
        (0, "limitations", "Small sample size", "limitations"),
        (0, "future_work", "Evaluate larger datasets", "future_work"),
        (1, "methodology", "A", "methodology"), (1, "datasets", "X", "experiments"),
        (1, "limitations", "Small sample size", "limitations"),
        (1, "future_work", "Evaluate larger datasets", "future_work"),
        (2, "methodology", "A", "methodology"), (2, "datasets", "X", "experiments"),
        (2, "limitations", "Small sample size", "limitations"),
        (3, "methodology", "B", "methodology"), (3, "datasets", "Y", "experiments"),
    ]
    extraction_ids = {}
    for paper_index, field_name, value, group in data:
        cursor = connection.execute(
            """INSERT INTO extractions
               (paper_id, group_name, field_name, item_index, field_value,
                confidence_score, confidence_level, review_required, status,
                section_detected, created_at, updated_at)
               VALUES (?, ?, ?, 0, ?, 0.8, 'HIGH', 0, 'ACCEPTED', 1, 'now', 'now')""",
            (papers[paper_index], group, field_name, value),
        )
        extraction_ids[(paper_index, field_name)] = cursor.lastrowid
    connection.commit()
    return connection, papers, extraction_ids


def test_gap_candidates_are_scoped_deterministic_and_traceable(tmp_path):
    connection, papers, extraction_ids = _analytics_db(tmp_path / "phase10.db")
    try:
        result = compare_papers(connection, papers)
    finally:
        connection.close()

    assert result["limitations"]["available"] is True
    future_frequency = result["future_work"]["frequencies"][0]
    assert future_frequency["count"] == 2
    assert {source["paper_id"] for source in future_frequency["sources"]} == set(papers[:2])
    assert {source["extraction_id"] for source in future_frequency["sources"]} == {
        extraction_ids[(i, "future_work")] for i in range(2)
    }
    assert any(p["rule"] == "repeated_value" and p["dimension"] == "limitations"
               for p in result["patterns"])
    assert any(p["rule"] == "repeated_value" and p["dimension"] == "future_work"
               for p in result["patterns"])
    candidates = result["gap_candidates"]
    dataset = next(c for c in candidates if c["type"] == "DATASET_CONCENTRATION")
    assert dataset["supporting_paper_ids"] == papers[:3]
    assert dataset["supporting_extraction_ids"] == [extraction_ids[(i, "datasets")] for i in range(3)]
    assert "3/4" in dataset["basis"] and "selected" in dataset["scope"].casefold()
    method = next(c for c in candidates if c["type"] == "METHOD_CONCENTRATION")
    assert method["supporting_paper_ids"] == papers[:3]
    recurring = next(c for c in candidates if c["type"] == "RECURRING_LIMITATION")
    assert recurring["supporting_extraction_ids"] == [extraction_ids[(i, "limitations")] for i in range(3)]
    future = next(c for c in candidates if c["type"] == "RECURRING_FUTURE_WORK")
    assert len(future["supporting_paper_ids"]) == 2
    sparse = next(c for c in candidates if c["type"] == "SPARSE_DIMENSION" and "evaluation metrics" in c["title"])
    assert sparse["supporting_extraction_ids"] == [extraction_ids[(0, "evaluation_metrics")]]
    absent = next(c for c in candidates if c["type"] == "METHOD_DATASET_ABSENCE" and "B × X" in c["title"])
    assert set(absent["supporting_extraction_ids"]) == {
        extraction_ids[(3, "methodology")], extraction_ids[(0, "datasets")],
        extraction_ids[(1, "datasets")], extraction_ids[(2, "datasets")],
    }
    assert "no selected paper" in absent["basis"].casefold()
    assert all(candidate["supporting_paper_ids"] and candidate["supporting_extraction_ids"]
               for candidate in candidates)


def test_comparison_api_returns_backward_compatible_and_phase10_fields(tmp_path, monkeypatch):
    db_path = tmp_path / "phase10-api.db"
    connection, papers, _ = _analytics_db(db_path)
    connection.close()
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setattr(main_module, "settings", replace(main_module.settings, database_path=db_path))
    with TestClient(main_module.app) as client:
        response = client.post("/api/v1/analytics/compare", json={"paper_ids": papers})
    assert response.status_code == 200
    body = response.json()
    assert all(key in body for key in (
        "selected_papers", "dimensions", "pairwise_differences",
        "missing_information", "patterns", "limitations", "future_work",
        "gap_candidates",
    ))


def test_gap_thresholds_are_configurable(tmp_path, monkeypatch):
    connection, papers, _ = _analytics_db(tmp_path / "phase10-threshold.db")
    monkeypatch.setenv("GAP_CONCENTRATION_THRESHOLD", "0.76")
    try:
        result = compare_papers(connection, papers)
    finally:
        connection.close()
    assert not any(candidate["type"] in {"DATASET_CONCENTRATION", "METHOD_CONCENTRATION"}
                   for candidate in result["gap_candidates"])


def test_limitations_and_future_work_use_existing_review_actions(tmp_path, monkeypatch):
    db_path = tmp_path / "phase10-review.db"
    connection = connect_database(db_path)
    initialize_schema(connection)
    ids = []
    for i, (group, value, action, reviewed) in enumerate((
        ("limitations", "AI limitation", "ACCEPT", None),
        ("future_work", "AI future work", "EDIT", "Reviewed future work"),
        ("limitations", "Another AI limitation", "REJECT", None),
    )):
        paper_id = create_paper(connection, f"review-{i}.pdf", str(i + 5) * 64)
        cursor = connection.execute(
            """INSERT INTO extractions
               (paper_id, group_name, field_name, item_index, field_value,
                status, section_detected, created_at, updated_at)
               VALUES (?, ?, ?, 0, ?, 'PENDING_REVIEW', 1, 'now', 'now')""",
            (paper_id, group, group, value),
        )
        ids.append((cursor.lastrowid, value, action, reviewed))
    connection.commit()
    connection.close()
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setattr(main_module, "settings", replace(main_module.settings, database_path=db_path))
    with TestClient(main_module.app) as client:
        for extraction_id, original, action, reviewed in ids:
            payload = {"action": action}
            if reviewed is not None:
                payload["reviewed_value"] = reviewed
            response = client.post(f"/api/v1/extractions/{extraction_id}/review", json=payload)
            assert response.status_code == 200
            body = response.json()
            assert body["field_value"] == original
            assert body["review"]["original_value"] == original
            assert body["status"] == {"ACCEPT": "ACCEPTED", "EDIT": "EDITED", "REJECT": "REJECTED"}[action]
            assert body["review"]["reviewed_value"] == reviewed
