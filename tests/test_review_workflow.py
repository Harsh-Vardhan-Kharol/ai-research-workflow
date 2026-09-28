"""Deterministic tests for extraction review actions and provenance."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config import get_settings
from app.database.connection import connect_database
from app.database.repository import (
    apply_extraction_review,
    create_paper,
    initialize_schema,
)
from app.schemas.extraction import GROUP_MODELS
from app.services.paper_processing import process_paper_text


def _pending_extraction(database_path: Path, status: str = "PENDING_REVIEW") -> int:
    connection = connect_database(database_path)
    try:
        initialize_schema(connection)
        paper_id = create_paper(connection, "review.pdf", "f" * 64)
        cursor = connection.execute(
            """INSERT INTO extractions
               (paper_id, group_name, field_name, item_index, field_value,
                proposed_source_text, proposed_page, proposed_section,
                confidence_score, confidence_level, confidence_signals,
                review_reasons, status, section_detected, review_required,
                created_at, updated_at)
               VALUES (?, 'research_problem', 'research_problem', 0,
                       'AI original', 'AI passage', 1, 'Introduction',
                       0.4, 'LOW', '{"schema_validity":1}',
                       '["low_confidence_score"]', ?, 1, 1, 'now', 'now')""",
            (paper_id, status),
        )
        connection.execute(
            """INSERT INTO evidence
               (extraction_id, page_number, section_name, source_text,
                evidence_score, page_corrected, match_status, created_at)
               VALUES (?, 1, 'Introduction', 'AI passage', 0.9, 0,
                       'MATCHED', 'now')""",
            (cursor.lastrowid,),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def _configure_database(monkeypatch, database_path: Path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setattr(
        main_module,
        "settings",
        replace(main_module.settings, database_path=database_path),
    )


@pytest.mark.parametrize(
    ("action", "status", "reviewed_value"),
    [
        ("ACCEPT", "ACCEPTED", None),
        ("EDIT", "EDITED", "Corrected value"),
        ("REJECT", "REJECTED", None),
    ],
)
def test_review_actions_persist_status_and_preserve_original(
    tmp_path, monkeypatch, action, status, reviewed_value
) -> None:
    database_path = tmp_path / "review.db"
    _configure_database(monkeypatch, database_path)
    extraction_id = _pending_extraction(database_path)

    request = {"action": action}
    if reviewed_value is not None:
        request["reviewed_value"] = reviewed_value
    if action == "REJECT":
        request["comment"] = "Not supported by the source."
    with TestClient(main_module.app) as client:
        response = client.post(
            f"/api/v1/extractions/{extraction_id}/review", json=request
        )
        assert response.status_code == 200
        body = response.json()
        assert body["field_value"] == "AI original"
        assert body["status"] == status
        assert body["review"]["original_value"] == "AI original"
        assert body["review"]["review_status"] == status
        assert body["review"]["reviewed_value"] == reviewed_value
        assert body["review"]["review_comment"] == (
            "Not supported by the source." if action == "REJECT" else None
        )

        fetched = client.get(f"/api/v1/extractions/{extraction_id}")
        assert fetched.status_code == 200
        assert fetched.json()["field_value"] == "AI original"
        assert fetched.json()["review"] == body["review"]

    connection = connect_database(database_path)
    try:
        item = connection.execute(
            """SELECT field_value, proposed_source_text, proposed_page,
                      proposed_section, confidence_score, confidence_level,
                      confidence_signals, review_reasons, status
               FROM extractions WHERE id = ?""",
            (extraction_id,),
        ).fetchone()
        records = connection.execute(
            "SELECT original_value, reviewed_value, review_status FROM review_records "
            "WHERE extraction_id = ?",
            (extraction_id,),
        ).fetchall()
        assert tuple(item) == (
            "AI original", "AI passage", 1, "Introduction", 0.4, "LOW",
            '{"schema_validity":1}', '["low_confidence_score"]', status,
        )
        evidence = connection.execute(
            """SELECT page_number, section_name, source_text, evidence_score,
                      match_status FROM evidence WHERE extraction_id = ?""",
            (extraction_id,),
        ).fetchone()
        assert tuple(evidence) == (1, "Introduction", "AI passage", 0.9, "MATCHED")
        assert len(records) == 1
        assert tuple(records[0]) == ("AI original", reviewed_value, status)
    finally:
        connection.close()


def test_invalid_review_payloads_and_values_are_rejected(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "validation.db"
    _configure_database(monkeypatch, database_path)
    extraction_id = _pending_extraction(database_path)
    with TestClient(main_module.app) as client:
        base = f"/api/v1/extractions/{extraction_id}/review"
        assert client.post(base, json={"action": "EDIT"}).status_code == 400
        unexpected_value = {"action": "ACCEPT", "reviewed_value": "x"}
        assert client.post(base, json=unexpected_value).status_code == 400
        assert client.post(base, json={"action": "maybe"}).status_code == 422
        malformed = {"action": "ACCEPT", "extra": True}
        assert client.post(base, json=malformed).status_code == 422
        assert client.post(
            base, json={"action": "EDIT", "reviewed_value": "  "}
        ).status_code == 422
        assert client.post(
            base, json={"action": "EDIT", "reviewed_value": 42}
        ).status_code == 422
        assert client.post(
            base, json={"action": "ACCEPT", "comment": "x" * 2001}
        ).status_code == 422
        assert client.post(
            "/api/v1/extractions/99999/review", json={"action": "ACCEPT"}
        ).status_code == 404


def test_paper_list_and_detail_api_reads(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "paper-views.db"
    _configure_database(monkeypatch, database_path)
    extraction_id = _pending_extraction(database_path)
    connection = connect_database(database_path)
    try:
        paper_id = connection.execute(
            "SELECT paper_id FROM extractions WHERE id = ?", (extraction_id,)
        ).fetchone()[0]
        connection.execute(
            "UPDATE papers SET title = ?, abstract = ?, authors = ?, publication_year = ? WHERE id = ?",
            ("Example study", "Abstract text", "A. Author", 2024, paper_id),
        )
        connection.commit()
    finally:
        connection.close()

    with TestClient(main_module.app) as client:
        listed = client.get("/api/v1/papers")
        assert listed.status_code == 200
        assert listed.json()["papers"][0]["id"] == paper_id
        assert listed.json()["papers"][0]["file_name"] == "review.pdf"
        assert listed.json()["papers"][0]["pending_review_count"] == 1

        detail = client.get(f"/api/v1/papers/{paper_id}")
        assert detail.status_code == 200
        assert detail.json()["title"] == "Example study"
        assert detail.json()["authors"] == "A. Author"
        assert detail.json()["extraction_counts_by_confidence"] == {"LOW": 1}
        assert client.get("/api/v1/papers/99999").status_code == 404


@pytest.mark.parametrize("status", ["ACCEPTED", "EDITED", "REJECTED", "EXTRACTED"])
def test_non_pending_and_duplicate_reviews_conflict(
    tmp_path, monkeypatch, status
) -> None:
    database_path = tmp_path / f"{status.lower()}.db"
    _configure_database(monkeypatch, database_path)
    extraction_id = _pending_extraction(database_path, status)
    with TestClient(main_module.app) as client:
        response = client.post(
            f"/api/v1/extractions/{extraction_id}/review", json={"action": "ACCEPT"}
        )
    assert response.status_code == 409
    assert response.json()["error"]["current_status"] == status


def test_review_transaction_rolls_back_if_record_insert_fails(tmp_path) -> None:
    database_path = tmp_path / "rollback.db"
    extraction_id = _pending_extraction(database_path)
    connection = connect_database(database_path)
    try:
        connection.execute(
            """CREATE TRIGGER reject_review BEFORE INSERT ON review_records
               BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END"""
        )
        connection.commit()
        with pytest.raises(sqlite3.IntegrityError):
            apply_extraction_review(connection, extraction_id, "ACCEPT", None, None)
        status = connection.execute(
            "SELECT status FROM extractions WHERE id = ?", (extraction_id,)
        ).fetchone()[0]
        count = connection.execute("SELECT COUNT(*) FROM review_records").fetchone()[0]
        assert status == "PENDING_REVIEW"
        assert count == 0
    finally:
        connection.close()


def _claim(value: str | None) -> dict[str, object]:
    return {"value": value, "source_text": None, "page": None, "section": None}


class _FakeReviewProvider:
    """Provider fixture returning schema-valid values with unavailable evidence."""

    def structured_complete(self, system_prompt, user_prompt, json_schema):
        fields = set(json_schema["properties"])
        group = next(
            key for key, model in GROUP_MODELS.items()
            if fields == set(model.model_fields)
        )
        values = {
            "metadata": {
                "title": _claim("Study"),
                "authors": [_claim("A. Author")],
                "publication_year": _claim("2024"),
                "abstract": _claim("Abstract"),
            },
            "research_problem": {
                "research_problem": _claim("AI problem"),
                "research_objective": _claim(None),
            },
            "methodology": {
                "methodology": _claim("AI method"),
                "models_algorithms": [],
            },
            "experiments": {
                "datasets": [],
                "experimental_setup": _claim(None),
                "evaluation_metrics": [],
            },
            "results": {"key_results": [_claim("AI result")]},
        }
        return values[group]


def test_pipeline_routes_pending_extraction_through_review_api(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "pipeline.db"
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    _configure_database(monkeypatch, database_path)
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Study\nAbstract\nAn abstract.\nIntroduction\nText")
    pdf_path = upload_directory / ("a" * 64 + ".pdf")
    document.save(pdf_path)
    document.close()

    connection = connect_database(database_path)
    try:
        initialize_schema(connection)
        paper_id = create_paper(connection, "paper.pdf", "a" * 64)
    finally:
        connection.close()
    process_paper_text(
        paper_id, database_path, upload_directory, _FakeReviewProvider()
    )

    connection = connect_database(database_path)
    try:
        paper_status = connection.execute(
            "SELECT status FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()[0]
        pending_id = connection.execute(
            """SELECT id FROM extractions WHERE status = 'PENDING_REVIEW'
               AND field_name = 'research_problem'"""
        ).fetchone()[0]
        assert paper_status == "READY"
    finally:
        connection.close()

    with TestClient(main_module.app) as client:
        listed = client.get(f"/api/v1/papers/{paper_id}/extractions").json()
        pending = next(
            item for item in listed["extractions"] if item["id"] == pending_id
        )
        assert pending["review_required"] is True
        result = client.post(
            f"/api/v1/extractions/{pending_id}/review",
            json={"action": "EDIT", "reviewed_value": "Human correction"},
        )
        assert result.status_code == 200
        assert result.json()["status"] == "EDITED"
        assert result.json()["field_value"] == "AI problem"
        assert result.json()["review"]["reviewed_value"] == "Human correction"
        fetched = client.get(f"/api/v1/extractions/{pending_id}").json()
        assert fetched["status"] == "EDITED"
        assert fetched["field_value"] == "AI problem"
        assert fetched["review"]["original_value"] == "AI problem"
        assert fetched["review"]["reviewed_value"] == "Human correction"
        paper_status = client.get(f"/api/v1/papers/{paper_id}/status").json()
        assert paper_status["status"] == "READY"
