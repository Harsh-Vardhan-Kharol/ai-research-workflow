"""Response models for PDF ingestion and processing status."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PaperUploadResponse(BaseModel):
    id: int
    status: str
    file_name: str


class PaperProcessResponse(BaseModel):
    status: str


class PaperStatusResponse(BaseModel):
    status: str
    failure_reason: str | None


class PaperListItemResponse(BaseModel):
    id: int
    title: str | None
    file_name: str
    status: str
    created_at: str
    updated_at: str
    pending_review_count: int


class PaperListResponse(BaseModel):
    papers: list[PaperListItemResponse]


class PaperDetailResponse(PaperListItemResponse):
    abstract: str | None
    authors: str | None
    publication_year: int | None
    source: str | None
    failure_reason: str | None
    extraction_counts_by_confidence: dict[str, int]


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
    confidence_signals: dict[str, float] | None
    review_required: bool
    review_reasons: list[str] | None
    status: str
    section_detected: bool
    evidence: EvidenceSummary | None
    review: "ReviewRecordResponse | None" = None


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["ACCEPT", "EDIT", "REJECT"]
    reviewed_value: str | None = Field(default=None, max_length=12000)
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("reviewed_value")
    @classmethod
    def normalize_reviewed_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("reviewed_value must not be empty")
        return cleaned

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ReviewRecordResponse(BaseModel):
    original_value: str
    reviewed_value: str | None
    review_status: Literal["ACCEPTED", "EDITED", "REJECTED"]
    review_comment: str | None
    reviewed_at: str


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
