"""Deterministic evidence matching tests against supplied stored page text."""

from __future__ import annotations

import pytest
from dataclasses import replace

import app.main as main_module
from app.api.routes import papers as papers_routes
from app.core.config import get_settings
from app.database.connection import connect_database
from app.database.repository import (
    create_paper,
    initialize_schema,
    replace_extraction_group_results,
    set_paper_status,
)
from fastapi.testclient import TestClient
from app.services.evidence_mapper import (
    EvidenceMapper,
    MalformedEvidenceSource,
)
from app.services.paper_processing import _score_paper_confidence


def test_exact_match_uses_stored_page_and_resolves_consistent_section() -> None:
    mapper = EvidenceMapper()
    result = mapper.map_source(
        "We propose a transformer model.",
        2,
        {2: "Intro. We propose a transformer model."},
        [
            {
                "section_name": "Methodology",
                "start_page": 2,
                "end_page": 2,
                "content": "We propose a transformer model.",
            }
        ],
    )

    assert result.match_status == "MATCHED"
    assert result.evidence_score == 1.0
    assert result.page_number == 2
    assert result.section_name == "Methodology"
    assert result.source_text == "We propose a transformer model"
    assert result.page_corrected is False


def test_whitespace_differences_are_normalized() -> None:
    result = EvidenceMapper().map_source(
        "The model\n  reached a high score.",
        1,
        {1: "The model reached\n\na high score."},
        [],
    )
    assert result.match_status == "MATCHED"
    assert result.evidence_score == 1.0


def test_punctuation_differences_are_normalized() -> None:
    result = EvidenceMapper().map_source(
        "We use a transformer-based architecture.",
        1,
        {1: "We use a transformer based architecture; see Fig. 2."},
        [],
    )
    assert result.match_status == "MATCHED"
    assert result.evidence_score == 1.0


def test_partial_source_passage_returns_actual_matched_span() -> None:
    result = EvidenceMapper().map_source(
        "The paper states: We propose a hybrid neural architecture for this task.",
        1,
        {1: "We propose a hybrid neural architecture."},
        [],
    )
    assert result.match_status == "MATCHED"
    assert result.source_text == "We propose a hybrid neural architecture"
    assert result.evidence_score == 1.0


def test_invalid_page_falls_back_and_marks_page_corrected() -> None:
    result = EvidenceMapper().map_source(
        "The evaluation uses the MNIST dataset.",
        77,
        {
            1: "Introduction with background.",
            4: "The evaluation uses the MNIST dataset.",
        },
        [],
    )
    assert result.match_status == "MATCHED"
    assert result.page_number == 4
    assert result.page_corrected is True


def test_missing_page_falls_back_across_all_pages() -> None:
    result = EvidenceMapper().map_source(
        "We release the source code.",
        None,
        {3: "Discussion.", 5: "We release the source code."},
        [],
    )
    assert result.page_number == 5
    assert result.page_corrected is True


def test_missing_source_is_unavailable_without_fabricating_text() -> None:
    result = EvidenceMapper().map_source(None, 1, {1: "Stored text."}, [])
    assert result.match_status == "UNAVAILABLE"
    assert result.failure_code == "missing_source"
    assert result.source_text == ""
    assert result.page_number is None
    assert result.evidence_score == 0.0


def test_no_matching_text_is_unavailable() -> None:
    result = EvidenceMapper().map_source(
        "zzzzzzzzzz",
        1,
        {1: "aaaaaaaaaa"},
        [],
    )
    assert result.match_status == "UNAVAILABLE"
    assert result.failure_code == "no_match"
    assert result.evidence_score == 0.0
    assert result.source_text == ""


def test_weak_match_retains_score_and_candidate() -> None:
    result = EvidenceMapper(0.9).map_source(
        "The model is not effective.",
        1,
        {1: "A different method was proposed."},
        [],
    )
    assert result.match_status == "WEAK"
    assert result.evidence_score == pytest.approx(0.4255319149)
    assert result.source_text


def test_multiple_candidates_choose_best_then_lowest_page_on_tie() -> None:
    result = EvidenceMapper().map_source(
        "The model improves accuracy.",
        None,
        {
            9: "The model improves accuracy.",
            2: "The model improves accuracy.",
            4: "A model is evaluated.",
        },
        [],
    )
    assert result.page_number == 2
    assert result.page_corrected is True


def test_section_is_resolved_from_actual_page_content_not_proposal() -> None:
    result = EvidenceMapper().map_source(
        "We compare all evaluation outcomes.",
        3,
        {3: "We compare all evaluation outcomes."},
        [
            {
                "section_name": "Methodology",
                "start_page": 3,
                "end_page": 3,
                "content": "We design the study.",
            },
            {
                "section_name": "Results",
                "start_page": 3,
                "end_page": 3,
                "content": "We compare all evaluation outcomes.",
            },
        ],
    )
    assert result.section_name == "Results"


@pytest.mark.parametrize("source", [[], {}, 3])
def test_malformed_source_is_reported(source) -> None:
    with pytest.raises(MalformedEvidenceSource):
        EvidenceMapper().map_source(source, 1, {1: "text"}, [])


def test_api_exposes_proposal_and_independently_matched_evidence(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "evidence.db"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setattr(
        main_module,
        "settings",
        replace(main_module.settings, database_path=database_path),
    )
    monkeypatch.setattr(
        papers_routes,
        "get_settings",
        lambda: replace(get_settings(), database_path=database_path),
    )
    connection = connect_database(database_path)
    try:
        initialize_schema(connection)
        paper_id = create_paper(connection, "paper.pdf", "c" * 64)
        connection.execute(
            "INSERT INTO paper_pages (paper_id, page_number, text) VALUES (?, ?, ?)",
            (paper_id, 2, "Actual method passage in the paper."),
        )
        connection.commit()
        replace_extraction_group_results(
            connection,
            paper_id,
            "methodology",
            [
                {
                    "field_name": "methodology",
                    "item_index": 0,
                    "field_value": "Method claim",
                    "proposed_source_text": "Actual method passage in the paper.",
                    "proposed_page": 99,
                    "proposed_section": "Unverified section",
                    "section_detected": True,
                    "evidence": {
                        "page_number": 2,
                        "section_name": None,
                        "source_text": "Actual method passage in the paper",
                        "evidence_score": 1.0,
                        "page_corrected": True,
                        "match_status": "MATCHED",
                        "failure_code": None,
                    },
                }
            ],
        )
        extraction_id = connection.execute(
            "SELECT id FROM extractions WHERE paper_id = ?", (paper_id,)
        ).fetchone()[0]
        set_paper_status(connection, paper_id, "SCORING_CONFIDENCE")
        _score_paper_confidence(connection, paper_id)
    finally:
        connection.close()

    with TestClient(main_module.app) as client:
        paper_response = client.get(f"/api/v1/papers/{paper_id}/extractions")
        item = paper_response.json()["extractions"][0]
        assert item["proposed_page"] == 99
        assert item["evidence"]["page_number"] == 2
        assert item["confidence_score"] == 0.8
        assert item["confidence_level"] == "HIGH"
        assert item["confidence_signals"] == {
            "schema_validity": 1.0,
            "evidence_strength": 1.0,
            "source_relevance": 0.0,
            "completeness": 1.0,
        }
        assert item["review_required"] is False
        assert item["review_reasons"] == []
        detail_response = client.get(f"/api/v1/extractions/{extraction_id}")
        assert detail_response.status_code == 200
        assert detail_response.json()["confidence_score"] == 0.8
        assert (
            detail_response.json()["confidence_signals"]
            == item["confidence_signals"]
        )
        evidence_response = client.get(
            f"/api/v1/extractions/{extraction_id}/evidence"
        )
        evidence = evidence_response.json()
        assert evidence["proposed_section"] == "Unverified section"
        assert evidence["section_name"] is None
        assert evidence["matched_source_text"] == "Actual method passage in the paper"
        assert evidence["match_status"] == "MATCHED"
