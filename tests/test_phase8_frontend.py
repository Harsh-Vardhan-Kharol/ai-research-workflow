"""Focused checks for Phase 8's API client and presentation helpers."""

from __future__ import annotations

import requests
import pytest

from frontend.api_client import ApiClientError, ResearchFlowApi
from frontend.components.extraction_card import group_extractions
from frontend.components.review_controls import validate_comment, validate_edit
from frontend.components.comparison_view import frequency_rows, pairwise_rows, gap_candidate_rows


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self.body = body or {}

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_api_client_parses_success_and_constructs_review_request():
    response_body = {
        "id": 17, "field_value": "original", "status": "EDITED", "review": {}
    }
    session = FakeSession(FakeResponse(body=response_body))
    api = ResearchFlowApi("http://api.local/", session=session)

    response = api.review_extraction(
        17, "EDIT", reviewed_value=" corrected ", comment=" checked "
    )

    assert response == response_body
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "http://api.local/api/v1/extractions/17/review"
    assert kwargs["json"] == {
        "action": "EDIT", "reviewed_value": " corrected ", "comment": "checked"
    }
    assert kwargs["timeout"] == 10.0


def test_api_client_reports_http_and_connection_errors_safely():
    conflict = FakeSession(FakeResponse(409, {"error": {"code": "REVIEW_CONFLICT"}}))
    with pytest.raises(ApiClientError, match="no longer pending") as error:
        ResearchFlowApi(session=conflict).review_extraction(4, "ACCEPT")
    assert error.value.status_code == 409

    offline = FakeSession(requests.ConnectionError())
    with pytest.raises(ApiClientError, match="Backend unavailable"):
        ResearchFlowApi(session=offline).list_papers()

    malformed = FakeSession(FakeResponse(body={"papers": [{"id": 3}]}))
    with pytest.raises(ApiClientError, match="malformed paper data"):
        ResearchFlowApi(session=malformed).list_papers()


def test_edit_validation_trims_and_enforces_backend_limits():
    assert validate_edit("  corrected  ") == "corrected"
    assert validate_comment("  note ") == "note"
    assert validate_comment("  ") is None
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_edit("  ")
    with pytest.raises(ValueError, match="12,000"):
        validate_edit("x" * 12001)
    with pytest.raises(ValueError, match="2,000"):
        validate_comment("x" * 2001)


def test_extractions_are_grouped_by_backend_group_name():
    items = [
        {"group_name": "metadata", "id": 1},
        {"group_name": "results", "id": 2},
        {"group_name": "metadata", "id": 3},
    ]
    assert group_extractions(items) == {
        "metadata": [items[0], items[2]], "results": [items[1]]
    }


def test_comparison_client_posts_ids_and_validates_response():
    body = {
        "selected_papers": [], "dimensions": [], "pairwise_differences": [],
        "missing_information": [], "patterns": [], "limitations": {},
        "future_work": {}, "gap_candidates": [],
    }
    session = FakeSession(FakeResponse(body=body))
    api = ResearchFlowApi("http://api.local", session=session)
    assert api.compare_papers([3, 7]) == body
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "http://api.local/api/v1/analytics/compare"
    assert kwargs["json"] == {"paper_ids": [3, 7]}

    malformed = FakeSession(FakeResponse(body={"dimensions": []}))
    with pytest.raises(ApiClientError, match="malformed data"):
        ResearchFlowApi(session=malformed).compare_papers([3, 7])


def test_comparison_view_helpers_keep_paper_traceability():
    dimension = {"frequencies": [{
        "normalized_value": "random forest", "original_values": ["Random Forest"],
        "paper_ids": [1, 2], "count": 2, "sources": [{"extraction_id": 14}],
    }]}
    papers = {1: {"title": "Paper A"}, 2: {"file_name": "b.pdf"}}
    rows = frequency_rows(dimension, papers)
    assert rows[0]["Papers"] == "Paper A, b.pdf"
    assert rows[0]["Paper IDs"] == [1, 2]
    assert rows[0]["Source records"] == [{"extraction_id": 14}]
    comparison = {"pairwise_differences": [{
        "first_paper_id": 1, "second_paper_id": 2,
        "dimensions": [{"dimension": "datasets", "first_reported": True,
                        "second_reported": True, "first_only": ["x"],
                        "second_only": ["y"], "shared_values": []}],
    }]}
    assert pairwise_rows(comparison, papers)[0]["Paper A"] == "x"


def test_gap_candidate_view_rows_preserve_basis_and_traceability():
    candidate = {
        "type": "DATASET_CONCENTRATION", "title": "Limited dataset diversity",
        "scope": "Selected 3-paper comparison", "basis": "Dataset X appears in 2/3.",
        "supporting_paper_ids": [1, 2], "supporting_extraction_ids": [10, 11],
        "sources": [{"paper_id": 1, "extraction_id": 10}],
    }
    row = gap_candidate_rows([candidate], {1: {"title": "Paper A"}, 2: {"title": "Paper B"}})[0]
    assert row["Basis"] == candidate["basis"]
    assert row["Paper IDs"] == [1, 2]
    assert row["Papers"] == ["Paper A", "Paper B"]
    assert row["Extraction IDs"] == [10, 11]
    assert row["Sources"] == candidate["sources"]
