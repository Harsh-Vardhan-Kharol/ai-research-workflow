"""Phase 9 deterministic comparison, selection, and traceability tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.database.connection import connect_database
from app.database.repository import create_paper, initialize_schema
from app.services.comparison_service import ComparisonSelectionError, compare_papers
from app.services.normalization import normalize_comparison_value


def _fixture_db(path):
    connection = connect_database(path)
    initialize_schema(connection)
    papers = []
    for index, title in enumerate(("Paper A", "Paper B", "Paper C"), start=1):
        paper_id = create_paper(connection, f"paper-{index}.pdf", str(index) * 64)
        connection.execute(
            "UPDATE papers SET title = ?, status = 'READY' WHERE id = ?",
            (title, paper_id),
        )
        papers.append(paper_id)
    values = [
        (papers[0], "models_algorithms", "Random Forest", "HIGH", "ACCEPTED"),
        (papers[0], "datasets", "Dataset X", "MEDIUM", "PENDING_REVIEW"),
        (papers[0], "evaluation_metrics", "Accuracy", "HIGH", "ACCEPTED"),
        (papers[0], "research_objective", "Detect fraud", "HIGH", "ACCEPTED"),
        (papers[1], "methodology", "random-forest", "LOW", "PENDING_REVIEW"),
        (papers[1], "datasets", "Dataset X", "HIGH", "ACCEPTED"),
        (papers[1], "evaluation_metrics", "F1-score", "HIGH", "EDITED"),
        (papers[2], "models_algorithms", "XGBoost", "HIGH", "ACCEPTED"),
        (papers[2], "datasets", "Dataset Y", "HIGH", "ACCEPTED"),
        (papers[2], "evaluation_metrics", "Accuracy", "HIGH", "ACCEPTED"),
    ]
    for paper_id, field, value, level, status in values:
        cursor = connection.execute(
            """INSERT INTO extractions
               (paper_id, group_name, field_name, item_index, field_value,
                confidence_score, confidence_level, review_required, status,
                section_detected, created_at, updated_at)
               VALUES (?, 'comparison_test', ?, 0, ?, 0.8, ?, ?, ?, 1, 'now', 'now')""",
            (paper_id, field, value, level, int(status == "PENDING_REVIEW"), status),
        )
        if status in {"ACCEPTED", "EDITED", "PENDING_REVIEW"}:
            connection.execute(
                """INSERT INTO evidence
                   (extraction_id, source_text, evidence_score, page_corrected,
                    match_status, created_at)
                   VALUES (?, 'source passage', 0.8, 0, 'MATCHED', 'now')""",
                (cursor.lastrowid,),
            )
        if field == "evaluation_metrics" and status == "EDITED":
            connection.execute(
                """INSERT INTO review_records
                   (extraction_id, original_value, reviewed_value, review_status,
                    reviewed_at) VALUES (?, ?, 'Human edited metric', 'EDITED', 'now')""",
                (cursor.lastrowid, value),
            )
    connection.execute(
        """INSERT INTO extractions
           (paper_id, group_name, field_name, item_index, field_value,
            status, section_detected, created_at, updated_at)
           VALUES (?, 'comparison_test', 'models_algorithms', 1, 'Rejected method',
                   'REJECTED', 1, 'now', 'now')""",
        (papers[2],),
    )
    connection.commit()
    return connection, papers


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Random Forest", "random forest"),
        ("  random   forest  ", "random forest"),
        ("Random-Forest", "random forest"),
        ("XGBoost Classifier", "xgboost classifier"),
        ("XGBoost", "xgboost"),
        ("Transformer", "transformer"),
        ("BERT", "bert"),
    ],
)
def test_comparison_normalization_is_conservative(value, expected):
    assert normalize_comparison_value(value) == expected


def test_comparison_frequencies_trace_sources_and_preserve_original_values(tmp_path):
    connection, ids = _fixture_db(tmp_path / "compare.db")
    try:
        result = compare_papers(connection, ids)
        methods = next(d for d in result["dimensions"] if d["name"] == "methodology_models")
        random_forest = next(f for f in methods["frequencies"] if f["normalized_value"] == "random forest")
        assert random_forest["count"] == 2
        assert random_forest["paper_ids"] == ids[:2]
        assert random_forest["original_values"] == ["Random Forest", "random-forest"]
        assert [s["extraction_status"] for s in random_forest["sources"]] == ["ACCEPTED", "PENDING_REVIEW"]
        datasets = next(d for d in result["dimensions"] if d["name"] == "datasets")
        dataset_x = next(f for f in datasets["frequencies"] if f["normalized_value"] == "dataset x")
        assert dataset_x["paper_ids"] == ids[:2]
        assert dataset_x["count"] == 2
        assert methods["papers"][0]["values"][0]["original_value"] == "Random Forest"
        assert all(source["original_value"] != "Rejected method" for row in methods["frequencies"] for source in row["sources"])
        metrics = next(d for d in result["dimensions"] if d["name"] == "evaluation_metrics")
        edited = next(f for f in metrics["frequencies"] if f["normalized_value"] == "f1 score")["sources"][0]
        assert edited["original_value"] == "F1-score"
        assert edited["reviewed_value"] == "Human edited metric"
        assert edited["review_status"] == "EDITED"
    finally:
        connection.close()


def test_pairwise_differences_missingness_patterns_and_unavailable_limitations(tmp_path):
    connection, ids = _fixture_db(tmp_path / "analytics.db")
    try:
        result = compare_papers(connection, ids)
        first_pair = result["pairwise_differences"][0]
        datasets = next(d for d in first_pair["dimensions"] if d["dimension"] == "datasets")
        assert datasets["shared_values"] == ["dataset x"]
        metrics = next(d for d in first_pair["dimensions"] if d["dimension"] == "evaluation_metrics")
        assert metrics["first_only"] == ["accuracy"]
        assert metrics["second_only"] == ["f1 score"]
        objective = next(m for m in result["missing_information"] if m["dimension"] == "research_problem_objective")
        assert objective["reported_by_count"] == 1
        sparse = [p for p in result["patterns"] if p["rule"] == "sparse_field"]
        assert any(p["dimension"] == "research_problem_objective" for p in sparse)
        limitation = next(d for d in result["dimensions"] if d["name"] == "limitations")
        assert limitation["available"] is False and limitation["frequencies"] == []
        assert any(p["rule"] == "repeated_value" and p["normalized_value"] == "random forest" for p in result["patterns"])
        assert any(p["rule"] == "methodological_variation" for p in result["patterns"])
    finally:
        connection.close()


def test_selection_errors_cover_too_few_missing_and_ineligible(tmp_path):
    connection, ids = _fixture_db(tmp_path / "selection.db")
    try:
        with pytest.raises(ComparisonSelectionError, match="at least two"):
            compare_papers(connection, ids[:1])
        with pytest.raises(ComparisonSelectionError) as error:
            compare_papers(connection, [ids[0], 9999])
        assert error.value.status_code == 404
        connection.execute("UPDATE papers SET status = 'FAILED' WHERE id = ?", (ids[2],))
        with pytest.raises(ComparisonSelectionError) as error:
            compare_papers(connection, [ids[0], ids[2]])
        assert error.value.status_code == 409
    finally:
        connection.close()


def test_comparison_api_validates_request_and_returns_machine_readable_result(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    connection, ids = _fixture_db(db_path)
    connection.close()
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setattr(main_module, "settings", replace(main_module.settings, database_path=db_path))
    with TestClient(main_module.app) as client:
        response = client.post("/api/v1/analytics/compare", json={"paper_ids": ids})
        assert response.status_code == 200
        body = response.json()
        assert len(body["selected_papers"]) == 3
        assert {item["name"] for item in body["dimensions"]} >= {"datasets", "methodology_models", "limitations"}
        assert client.post("/api/v1/analytics/compare", json={"paper_ids": [ids[0]]}).status_code == 422
        duplicate = client.post("/api/v1/analytics/compare", json={"paper_ids": [ids[0], ids[0]]})
        assert duplicate.status_code == 422
        missing = client.post("/api/v1/analytics/compare", json={"paper_ids": [ids[0], 9999]})
        assert missing.status_code == 404
        connection = connect_database(db_path)
        try:
            connection.execute("UPDATE papers SET status = 'FAILED' WHERE id = ?", (ids[2],))
            connection.commit()
        finally:
            connection.close()
        ineligible = client.post("/api/v1/analytics/compare", json={"paper_ids": [ids[0], ids[2]]})
        assert ineligible.status_code == 409
