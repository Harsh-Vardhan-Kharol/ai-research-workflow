"""Unit tests for deterministic confidence math and evidence-driven routing."""

from __future__ import annotations

import math

import pytest

from app.services.confidence import (
    ConfidenceInputError,
    calculate_confidence,
    route_for_review,
    validate_evidence,
)
from app.database.connection import connect_database
from app.database.repository import (
    create_paper,
    get_extractions_for_paper,
    get_paper,
    initialize_schema,
    replace_extraction_group_results,
    set_paper_status,
)
from app.services.paper_processing import (
    _completeness,
    _score_paper_confidence,
    _source_relevance,
)


def signals(value: float) -> dict[str, float]:
    return {
        "schema_validity": value,
        "evidence_strength": value,
        "source_relevance": value,
        "completeness": value,
    }


@pytest.mark.parametrize(
    ("value", "score", "level"),
    [
        (1.0, 1.0, "HIGH"),
        (0.0, 0.0, "LOW"),
        (0.5, 0.5, "MEDIUM"),
        (0.449, 0.449, "LOW"),
        (0.44999, 0.44999, "LOW"),
        (0.45, 0.45, "MEDIUM"),
        (0.45001, 0.45001, "MEDIUM"),
        (0.749, 0.749, "MEDIUM"),
        (0.74999, 0.74999, "MEDIUM"),
        (0.75, 0.75, "HIGH"),
        (0.75001, 0.75001, "HIGH"),
    ],
)
def test_equal_signal_combinations_and_thresholds(value, score, level) -> None:
    result = calculate_confidence(signals(value))
    assert result.score == score
    assert result.level == level
    assert 0 <= result.score <= 1


def test_weighted_mixed_signals_are_transparent() -> None:
    result = calculate_confidence(
        {
            "schema_validity": 1.0,
            "evidence_strength": 0.8,
            "source_relevance": 0.5,
            "completeness": 1.0,
        }
    )
    assert result.score == 0.82
    assert result.level == "HIGH"
    assert result.signals["evidence_strength"] == 0.8


@pytest.mark.parametrize(
    ("state", "score", "contribution", "requires_review", "reason"),
    [
        ("MATCHED", 0.9, 0.9, False, None),
        ("WEAK", 0.2, 0.0, True, "evidence_weak"),
        ("UNAVAILABLE", 0.0, 0.0, True, "evidence_unavailable"),
        ("FAILED", 0.0, 0.0, True, "evidence_mapping_failed"),
    ],
)
def test_evidence_states_control_strength_and_routing(
    state, score, contribution, requires_review, reason
) -> None:
    record = {
        "match_status": state,
        "evidence_score": score,
        "source_text": "matched passage" if state in {"MATCHED", "WEAK"} else "",
        "page_number": 3 if state in {"MATCHED", "WEAK"} else None,
        "section_name": "Results" if state in {"MATCHED", "WEAK"} else None,
    }
    actual_state, actual_contribution = validate_evidence(record)
    assert (actual_state, actual_contribution) == (state, contribution)
    routed = route_for_review(calculate_confidence(signals(1.0)), state)
    assert routed.review_required is requires_review
    assert routed.review_reasons == ([reason] if reason else [])


def test_missing_evidence_scores_available_signals_but_requires_review() -> None:
    state, strength = validate_evidence(None)
    result = route_for_review(
        calculate_confidence(
            {
                "schema_validity": 1.0,
                "evidence_strength": strength,
                "source_relevance": 0.0,
                "completeness": 1.0,
            }
        ),
        state,
    )
    assert state == "UNAVAILABLE"
    assert strength == 0
    assert result.score == 0.4
    assert result.level == "LOW"
    assert result.review_required is True
    assert result.review_reasons == [
        "evidence_unavailable", "low_confidence_score"
    ]


def test_low_score_review_reason_is_independent() -> None:
    result = route_for_review(calculate_confidence(signals(0.2)), "MATCHED")
    assert result.level == "LOW"
    assert result.review_required is True
    assert result.review_reasons == ["low_confidence_score"]


def test_stronger_matched_evidence_never_reduces_score() -> None:
    low = calculate_confidence({**signals(1.0), "evidence_strength": 0.4})
    high = calculate_confidence({**signals(1.0), "evidence_strength": 0.9})
    assert high.score >= low.score


@pytest.mark.parametrize(
    ("group", "detected", "page", "section", "expected"),
    [
        ("methodology", True, 4, "Methodology", 1.0),
        ("methodology", True, 4, "Discussion", 0.0),
        ("methodology", False, 4, "Methodology", 0.5),
        ("metadata", False, 1, None, 1.0),
        ("metadata", True, None, None, 0.0),
    ],
)
def test_source_relevance_uses_verified_location(
    group, detected, page, section, expected
) -> None:
    assert _source_relevance(
        {"group_name": group, "section_detected": detected},
        {"page_number": page, "section_name": section},
    ) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("A complete sentence with a value.", 1.0),
        ("N/A", 0.0),
        ("Not reported", 0.0),
        ("  ", "invalid"),
        (None, "invalid"),
    ],
)
def test_completeness_is_presence_not_paper_coverage(value, expected) -> None:
    if expected == "invalid":
        with pytest.raises(ConfidenceInputError):
            _completeness(value)
    else:
        assert _completeness(value) == expected


@pytest.mark.parametrize(
    "value", [-0.01, 1.01, None, True, math.nan, math.inf, -math.inf]
)
def test_invalid_signal_values_are_rejected(value) -> None:
    with pytest.raises(ConfidenceInputError):
        calculate_confidence({**signals(1.0), "evidence_strength": value})


@pytest.mark.parametrize(
    "record",
    [
        {"match_status": "UNKNOWN", "evidence_score": 1},
        {"match_status": "MATCHED", "evidence_score": None,
         "source_text": "passage", "page_number": 1},
        {"match_status": "MATCHED", "evidence_score": math.nan,
         "source_text": "passage", "page_number": 1},
        {"match_status": "MATCHED", "evidence_score": 1.1,
         "source_text": "passage", "page_number": 1},
        {"match_status": "MATCHED", "evidence_score": 0.5,
         "source_text": "", "page_number": 1},
        {"match_status": "MATCHED", "evidence_score": 0.5,
         "source_text": "passage", "page_number": 0},
        {"match_status": "UNAVAILABLE", "evidence_score": 0.1,
         "source_text": "", "page_number": None},
        {"match_status": "MATCHED", "evidence_score": 0.2,
         "source_text": "passage", "page_number": 1},
        {"match_status": "WEAK", "evidence_score": 0.9,
         "source_text": "passage", "page_number": 1},
        {"match_status": "UNAVAILABLE", "evidence_score": 0.0,
         "source_text": None, "page_number": None},
        {"match_status": "FAILED", "evidence_score": 0.0,
         "source_text": "", "page_number": None, "page_corrected": 2},
    ],
)
def test_malformed_or_out_of_range_evidence_is_rejected(record) -> None:
    with pytest.raises(ConfidenceInputError):
        validate_evidence(record)


def test_missing_or_extra_signals_are_rejected() -> None:
    with pytest.raises(ConfidenceInputError):
        calculate_confidence({"schema_validity": 1.0})
    with pytest.raises(ConfidenceInputError):
        calculate_confidence({**signals(1.0), "llm_confidence": 1.0})


def test_persists_zero_evidence_review_and_ready_state(tmp_path) -> None:
    connection = connect_database(tmp_path / "confidence.db")
    try:
        initialize_schema(connection)
        paper_id = create_paper(connection, "paper.pdf", "f" * 64)
        replace_extraction_group_results(
            connection,
            paper_id,
            "methodology",
            [
                {
                    "field_name": "methodology",
                    "item_index": 0,
                    "field_value": "A validated method statement.",
                    "proposed_source_text": None,
                    "proposed_page": None,
                    "proposed_section": None,
                    "section_detected": True,
                    "evidence": {
                        "page_number": None,
                        "section_name": None,
                        "source_text": "",
                        "evidence_score": 0.0,
                        "page_corrected": False,
                        "match_status": "UNAVAILABLE",
                        "failure_code": "missing_source",
                    },
                }
            ],
        )
        set_paper_status(connection, paper_id, "SCORING_CONFIDENCE")
        _score_paper_confidence(connection, paper_id)

        paper = get_paper(connection, paper_id)
        extraction = get_extractions_for_paper(connection, paper_id)[0]
        assert paper["status"] == "READY"
        assert extraction["confidence_score"] == 0.4
        assert extraction["confidence_level"] == "LOW"
        assert extraction["confidence_signals"] == (
            '{"completeness": 1.0, "evidence_strength": 0.0, '
            '"schema_validity": 1.0, "source_relevance": 0.0}'
        )
        assert extraction["review_required"] == 1
        assert extraction["review_reasons"] == (
            '["evidence_unavailable", "low_confidence_score"]'
        )
        assert extraction["status"] == "PENDING_REVIEW"
    finally:
        connection.close()
