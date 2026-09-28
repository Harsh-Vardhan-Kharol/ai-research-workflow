"""Structured, compact inputs and traceable AI research insights."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

InsightType = Literal[
    "METHODOLOGICAL_PATTERN", "DATASET_PATTERN", "METRIC_PATTERN",
    "LIMITATION_PATTERN", "FUTURE_WORK_PATTERN",
    "GAP_CANDIDATE_INTERPRETATION", "RESEARCH_DIRECTION",
    "COMPARATIVE_OBSERVATION",
]
MAX_INSIGHTS_PER_COMPARISON = 10


class InsightSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    paper_id: int
    extraction_id: int
    value: str = Field(max_length=500)
    value_truncated: bool = False
    confidence_score: float | None = None
    confidence_level: str | None = Field(default=None, max_length=20)
    review_required: bool
    extraction_status: str = Field(max_length=30)
    review_status: str | None = Field(default=None, max_length=30)


class InsightFrequency(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dimension: str = Field(max_length=80)
    value: str = Field(max_length=500)
    count: int = Field(ge=1)
    selected_paper_count: int = Field(ge=2)
    paper_ids: list[int]
    extraction_ids: list[int]
    sources: list[InsightSource]


class InsightPattern(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reference_id: str = Field(pattern=r"^pattern:[0-9]+$", max_length=32)
    rule: str = Field(max_length=50)
    dimension: str = Field(max_length=80)
    count: int = Field(ge=0)
    paper_ids: list[int]
    extraction_ids: list[int]


class InsightCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reference_id: str = Field(pattern=r"^candidate:[0-9]+$", max_length=32)
    type: str = Field(max_length=50)
    title: str = Field(max_length=200)
    basis: str = Field(max_length=500)
    supporting_paper_ids: list[int]
    supporting_extraction_ids: list[int]


class InsightPaper(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: int
    title: str | None = Field(default=None, max_length=160)
    file_name: str | None = Field(default=None, max_length=120)


class InsightDifference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    paper_ids: list[int] = Field(min_length=2, max_length=2)
    dimension: str = Field(max_length=80)
    shared_values: list[str] = Field(max_length=8)
    first_only: list[str] = Field(max_length=8)
    second_only: list[str] = Field(max_length=8)


class InsightMissingInformation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dimension: str = Field(max_length=80)
    available: bool
    reported_by_count: int = Field(ge=0)
    selected_paper_count: int = Field(ge=2)
    paper_ids_not_reported: list[int]


class InsightInput(BaseModel):
    """Allowlisted serialization of deterministic analytics for interpretation."""

    model_config = ConfigDict(extra="forbid", strict=True)
    selected_papers: list[InsightPaper]
    selected_paper_count: int = Field(ge=2)
    frequencies: list[InsightFrequency]
    differences: list[InsightDifference]
    missing_information: list[InsightMissingInformation]
    patterns: list[InsightPattern]
    gap_candidates: list[InsightCandidate]


class ResearchInsight(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: InsightType
    title: str = Field(min_length=3, max_length=160)
    observation: str = Field(min_length=10, max_length=600)
    interpretation: str = Field(min_length=10, max_length=900)
    scope: str = Field(min_length=8, max_length=200)
    supporting_paper_ids: list[int] = Field(min_length=1, max_length=30)
    supporting_extraction_ids: list[int] = Field(min_length=1, max_length=100)
    supporting_pattern_ids: list[str] = Field(max_length=20)
    supporting_candidate_ids: list[str] = Field(max_length=20)
    suggested_research_question: str | None = Field(max_length=500)

    @model_validator(mode="after")
    def question_matches_type(self) -> "ResearchInsight":
        if not all((self.title.strip(), self.observation.strip(),
                    self.interpretation.strip(), self.scope.strip())):
            raise ValueError("Insight text fields must not be blank")
        if self.type == "RESEARCH_DIRECTION" and not self.suggested_research_question:
            raise ValueError("RESEARCH_DIRECTION requires a suggested research question")
        if self.type != "RESEARCH_DIRECTION" and self.suggested_research_question:
            raise ValueError("Suggested questions require RESEARCH_DIRECTION type")
        if self.type == "GAP_CANDIDATE_INTERPRETATION" and not self.supporting_candidate_ids:
            raise ValueError("Gap-candidate interpretations require a candidate reference")
        if self.type == "RESEARCH_DIRECTION" and not (
            self.supporting_candidate_ids or self.supporting_pattern_ids
        ):
            raise ValueError("Research directions require a pattern or candidate reference")
        if len(set(self.supporting_paper_ids)) != len(self.supporting_paper_ids):
            raise ValueError("supporting paper IDs must be unique")
        if len(set(self.supporting_extraction_ids)) != len(self.supporting_extraction_ids):
            raise ValueError("supporting extraction IDs must be unique")
        return self


class InsightGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    insights: list[ResearchInsight] = Field(max_length=MAX_INSIGHTS_PER_COMPARISON)


class InsightResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["completed"] = "completed"
    insights: list[ResearchInsight]
