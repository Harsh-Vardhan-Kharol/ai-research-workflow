"""Machine-readable deterministic comparison request and response models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    paper_ids: list[int] = Field(min_length=2)

    @field_validator("paper_ids")
    @classmethod
    def unique_papers(cls, values: list[int]) -> list[int]:
        if len(values) != len(set(values)):
            raise ValueError("paper_ids must not contain duplicates")
        return values


class SelectedPaper(BaseModel):
    id: int
    title: str | None
    file_name: str
    status: str


class ComparisonSource(BaseModel):
    extraction_id: int
    original_value: str
    confidence_score: float | None
    confidence_level: str | None
    review_required: bool
    extraction_status: str
    review_status: str | None
    reviewed_value: str | None


class PaperDimensionValues(BaseModel):
    paper_id: int
    reported: bool
    values: list[ComparisonSource]


class ComparisonFrequency(BaseModel):
    normalized_value: str
    original_values: list[str]
    paper_ids: list[int]
    count: int
    sources: list[ComparisonSource]


class ComparisonDimension(BaseModel):
    name: str
    available: bool
    papers: list[PaperDimensionValues]
    frequencies: list[ComparisonFrequency]


class DimensionDifference(BaseModel):
    dimension: str
    available: bool
    shared_values: list[str]
    first_only: list[str]
    second_only: list[str]
    first_reported: bool
    second_reported: bool


class PairwiseDifference(BaseModel):
    first_paper_id: int
    second_paper_id: int
    dimensions: list[DimensionDifference]


class MissingInformation(BaseModel):
    dimension: str
    available: bool
    reported_by_count: int
    selected_paper_count: int
    paper_ids_not_reported: list[int]


class ResearchPattern(BaseModel):
    rule: str
    dimension: str
    normalized_value: str | None = None
    paper_ids: list[int]
    count: int
    message: str


class GapCandidateSource(ComparisonSource):
    paper_id: int


class TraceableComparisonFrequency(ComparisonFrequency):
    sources: list[GapCandidateSource]


class GapCandidate(BaseModel):
    type: str
    title: str
    description: str
    scope: str
    basis: str
    supporting_paper_ids: list[int]
    supporting_extraction_ids: list[int]
    relevant_values: list[str]
    sources: list[GapCandidateSource]


class DimensionSummary(BaseModel):
    available: bool
    frequencies: list[TraceableComparisonFrequency]
    patterns: list[ResearchPattern]


class ComparisonResponse(BaseModel):
    selected_papers: list[SelectedPaper]
    dimensions: list[ComparisonDimension]
    pairwise_differences: list[PairwiseDifference]
    missing_information: list[MissingInformation]
    patterns: list[ResearchPattern]
    limitations: DimensionSummary
    future_work: DimensionSummary
    gap_candidates: list[GapCandidate]
