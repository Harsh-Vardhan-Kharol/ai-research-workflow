"""Small HTTP client for the implemented ResearchFlow API."""

from __future__ import annotations

import os
from typing import Any, BinaryIO

import requests


class ApiClientError(Exception):
    """Safe, user-displayable API failure."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ResearchFlowApi:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        session: Any = requests,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = (base_url or os.getenv(
            "RESEARCHFLOW_API_URL", "http://localhost:8000"
        )).rstrip("/")
        self.session = session
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.session.request(
                method, f"{self.base_url}/api/v1{path}", timeout=self.timeout,
                **kwargs,
            )
        except requests.Timeout as exc:
            raise ApiClientError("The backend request timed out.") from exc
        except requests.ConnectionError as exc:
            raise ApiClientError(
                "Backend unavailable. Make sure the FastAPI server is running."
            ) from exc
        except requests.RequestException as exc:
            raise ApiClientError("Could not communicate with the backend.") from exc

        if not 200 <= response.status_code < 300:
            message = self._error_message(response)
            raise ApiClientError(message, response.status_code)
        if response.status_code == 204:
            return None
        try:
            data = response.json()
        except (ValueError, requests.JSONDecodeError) as exc:
            raise ApiClientError("The backend returned an invalid response.", response.status_code) from exc
        if not isinstance(data, dict):
            raise ApiClientError("The backend returned an invalid response.", response.status_code)
        return data

    @staticmethod
    def _require_keys(data: dict[str, Any], *keys: str) -> dict[str, Any]:
        if not all(key in data for key in keys):
            raise ApiClientError("The backend returned malformed data.")
        return data

    @staticmethod
    def _error_message(response: Any) -> str:
        try:
            error = response.json().get("error", {})
            if response.status_code == 409 and error.get("code") == "REVIEW_CONFLICT":
                return "This extraction is no longer pending review. Refreshing its current state."
            message = error.get("message")
            if isinstance(message, str) and message:
                return message
        except (ValueError, AttributeError):
            pass
        return {
            404: "The requested paper or extraction was not found.",
            409: "The request conflicts with the current workflow state.",
            422: "Some submitted information is invalid. Check the values and try again.",
        }.get(response.status_code, "The backend could not complete the request.")

    def list_papers(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/papers")
        papers = data.get("papers")
        if not isinstance(papers, list) or not all(isinstance(x, dict) for x in papers):
            raise ApiClientError("The backend returned malformed paper data.")
        if any(not all(key in paper for key in ("id", "file_name", "status")) for paper in papers):
            raise ApiClientError("The backend returned malformed paper data.")
        return papers

    def get_paper(self, paper_id: int) -> dict[str, Any]:
        data = self._request("GET", f"/papers/{paper_id}")
        return self._require_keys(data, "id", "file_name", "status")

    def get_paper_status(self, paper_id: int) -> dict[str, Any]:
        data = self._request("GET", f"/papers/{paper_id}/status")
        return self._require_keys(data, "status", "failure_reason")

    def process_paper(self, paper_id: int) -> dict[str, Any]:
        data = self._request("POST", f"/papers/{paper_id}/process")
        return self._require_keys(data, "status")

    def get_extraction_groups(self, paper_id: int) -> dict[str, Any]:
        data = self._request("GET", f"/papers/{paper_id}/extraction-groups")
        groups = data.get("groups")
        if not isinstance(groups, list) or not all(isinstance(x, dict) for x in groups):
            raise ApiClientError("The backend returned malformed extraction-group data.")
        return data

    def get_extractions(self, paper_id: int) -> list[dict[str, Any]]:
        data = self._request("GET", f"/papers/{paper_id}/extractions")
        items = data.get("extractions")
        if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
            raise ApiClientError("The backend returned malformed extraction data.")
        required = ("id", "group_name", "field_name", "field_value", "status")
        if any(not all(key in item for key in required) for item in items):
            raise ApiClientError("The backend returned malformed extraction data.")
        return items

    def compare_papers(self, paper_ids: list[int]) -> dict[str, Any]:
        data = self._request("POST", "/analytics/compare", json={"paper_ids": paper_ids})
        required = (
            "selected_papers", "dimensions", "pairwise_differences",
            "missing_information", "patterns", "limitations", "future_work",
            "gap_candidates",
        )
        self._require_keys(data, *required)
        if any(not isinstance(data[key], list) for key in required[:5]) or any(
            not isinstance(data[key], dict) for key in ("limitations", "future_work")
        ) or not isinstance(data["gap_candidates"], list):
            raise ApiClientError("The backend returned malformed comparison data.")
        return data

    def generate_insights(self, paper_ids: list[int]) -> dict[str, Any]:
        data = self._request("POST", "/analytics/insights", json={"paper_ids": paper_ids})
        if data.get("status") != "completed" or not isinstance(data.get("insights"), list):
            raise ApiClientError("The backend returned malformed insight data.")
        required = ("type", "title", "observation", "interpretation", "scope",
                    "supporting_paper_ids", "supporting_extraction_ids")
        for insight in data["insights"]:
            if not isinstance(insight, dict) or not all(key in insight for key in required):
                raise ApiClientError("The backend returned malformed insight data.")
        return data

    def get_extraction(self, extraction_id: int) -> dict[str, Any]:
        data = self._request("GET", f"/extractions/{extraction_id}")
        return self._require_keys(data, "id", "field_value", "status", "evidence")

    def get_evidence(self, extraction_id: int) -> dict[str, Any]:
        data = self._request("GET", f"/extractions/{extraction_id}/evidence")
        return self._require_keys(data, "match_status", "matched_source_text")

    def review_extraction(
        self,
        extraction_id: int,
        action: str,
        *,
        reviewed_value: str | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": action}
        if reviewed_value is not None:
            payload["reviewed_value"] = reviewed_value
        if comment and comment.strip():
            payload["comment"] = comment.strip()
        data = self._request("POST", f"/extractions/{extraction_id}/review", json=payload)
        return self._require_keys(data, "id", "field_value", "status", "review")

    def upload_paper(self, file_name: str, file_obj: BinaryIO) -> dict[str, Any]:
        data = self._request(
            "POST", "/papers/upload", files={"file": (file_name, file_obj, "application/pdf")}
        )
        return self._require_keys(data, "id", "status", "file_name")
