"""Strict Pydantic schemas for the Phase 4 AI extraction payloads."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class Claim(BaseModel):
    """One explicitly stated value and the model's unverified source claim."""

    model_config = ConfigDict(extra="forbid", strict=True)

    value: str | None
    source_text: str | None
    page: int | None
    section: str | None

    @field_validator("value", "source_text", "section")
    @classmethod
    def strip_nonempty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text must not be empty")
        return cleaned

    @field_validator("page")
    @classmethod
    def positive_page(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("page must be a positive page number")
        return value

    @model_validator(mode="after")
    def null_value_has_no_claimed_evidence(self) -> Claim:
        if self.value is None and any(
            item is not None for item in (self.source_text, self.page, self.section)
        ):
            raise ValueError("a null value cannot claim supporting evidence")
        return self


class ExtractionPayload(BaseModel):
    """Base class enforcing exact output fields and strict input types."""

    model_config = ConfigDict(extra="forbid", strict=True)


class MetadataExtraction(ExtractionPayload):
    title: Claim
    authors: list[Claim]
    publication_year: Claim
    abstract: Claim


class ProblemExtraction(ExtractionPayload):
    research_problem: Claim
    research_objective: Claim


class MethodologyExtraction(ExtractionPayload):
    methodology: Claim
    models_algorithms: list[Claim]


class ExperimentsExtraction(ExtractionPayload):
    datasets: list[Claim]
    experimental_setup: Claim
    evaluation_metrics: list[Claim]


class ResultsExtraction(ExtractionPayload):
    key_results: list[Claim]


class LimitationsExtraction(ExtractionPayload):
    limitations: list[Claim]


class FutureWorkExtraction(ExtractionPayload):
    future_work: list[Claim]


GROUP_MODELS: dict[str, type[ExtractionPayload]] = {
    "metadata": MetadataExtraction,
    "research_problem": ProblemExtraction,
    "methodology": MethodologyExtraction,
    "experiments": ExperimentsExtraction,
    "results": ResultsExtraction,
    "limitations": LimitationsExtraction,
    "future_work": FutureWorkExtraction,
}
