"""Response models for PDF ingestion and processing status."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class PaperUploadResponse(BaseModel):
    id: int
    status: str
    file_name: str


class PaperProcessResponse(BaseModel):
    status: str


class PaperStatusResponse(BaseModel):
    status: str
    failure_reason: str | None


class ExtractionGroupResponse(BaseModel):
    group_name: str
    status: Literal["SUCCEEDED", "FAILED"]
    validated_payload: dict[str, Any] | None
    section_detected: bool
    truncated: bool
    failure_code: str | None


class PaperExtractionGroupsResponse(BaseModel):
    paper_id: int
    groups: list[ExtractionGroupResponse]


class EvidenceSummary(BaseModel):
    proposed_source_text: str | None
    proposed_page: int | None
    proposed_section: str | None
    page_number: int | None
    section_name: str | None
    matched_source_text: str
    evidence_score: float
    page_corrected: bool
    match_status: Literal["MATCHED", "WEAK", "UNAVAILABLE", "FAILED"]
    failure_code: str | None


class ExtractionItemResponse(BaseModel):
    id: int
    group_name: str
    field_name: str
    item_index: int
    field_value: str
    proposed_source_text: str | None
    proposed_page: int | None
    proposed_section: str | None
    confidence_score: float | None
    confidence_level: str | None
    status: str
    section_detected: bool
    evidence: EvidenceSummary | None


class PaperExtractionsResponse(BaseModel):
    paper_id: int
    extractions: list[ExtractionItemResponse]


class ExtractionEvidenceResponse(BaseModel):
    extraction_id: int
    field_name: str
    field_value: str
    proposed_source_text: str | None
    proposed_page: int | None
    proposed_section: str | None
    page_number: int | None
    section_name: str | None
    matched_source_text: str
    evidence_score: float
    page_corrected: bool
    match_status: Literal["MATCHED", "WEAK", "UNAVAILABLE", "FAILED"]
    failure_code: str | None
