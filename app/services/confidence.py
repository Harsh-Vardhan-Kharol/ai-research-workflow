"""Deterministic confidence scoring and review routing for extraction items."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping


WEIGHTS = {
    "schema_validity": 0.30,
    "evidence_strength": 0.40,
    "source_relevance": 0.20,
    "completeness": 0.10,
}
HIGH_THRESHOLD = 0.75
MEDIUM_THRESHOLD = 0.45
EVIDENCE_STATES = {"MATCHED", "WEAK", "UNAVAILABLE", "FAILED"}


class ConfidenceInputError(ValueError):
    """Confidence inputs are incomplete, corrupt, or outside their domain."""


@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    score: float
    level: str
    review_required: bool
    signals: dict[str, float]
    review_reasons: list[str]


def calculate_confidence(signals: Mapping[str, float]) -> ConfidenceResult:
    """Return the weighted score and level from four validated signals."""
    if not isinstance(signals, Mapping) or set(signals) != set(WEIGHTS):
        raise ConfidenceInputError("exactly four confidence signals are required")
    normalized: dict[str, float] = {}
    for name in WEIGHTS:
        value = signals[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfidenceInputError(f"{name} must be a finite number")
        numeric = float(value)
        if not math.isfinite(numeric) or not 0 <= numeric <= 1:
            raise ConfidenceInputError(f"{name} must be between 0 and 1")
        normalized[name] = numeric

    score = round(sum(normalized[name] * WEIGHTS[name] for name in WEIGHTS), 6)
    level = "HIGH" if score >= HIGH_THRESHOLD else (
        "MEDIUM" if score >= MEDIUM_THRESHOLD else "LOW"
    )
    return ConfidenceResult(score, level, False, normalized, [])


def validate_evidence(
    evidence: Mapping[str, object] | None,
    min_evidence_threshold: float = 0.35,
) -> tuple[str, float]:
    """Validate persisted evidence and return state and confidence contribution."""
    if evidence is None:
        return "UNAVAILABLE", 0.0
    if not isinstance(evidence, Mapping):
        raise ConfidenceInputError("evidence must be a mapping")
    if (
        isinstance(min_evidence_threshold, bool)
        or not isinstance(min_evidence_threshold, (int, float))
        or not math.isfinite(float(min_evidence_threshold))
        or not 0 <= float(min_evidence_threshold) <= 1
    ):
        raise ConfidenceInputError("evidence threshold must be between 0 and 1")
    state = evidence.get("match_status")
    if not isinstance(state, str) or state not in EVIDENCE_STATES:
        raise ConfidenceInputError("unknown evidence state")
    score = evidence.get("evidence_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ConfidenceInputError("evidence score must be a finite number")
    numeric = float(score)
    if not math.isfinite(numeric) or not 0 <= numeric <= 1:
        raise ConfidenceInputError("evidence score must be between 0 and 1")
    if state == "UNAVAILABLE" and numeric != 0:
        raise ConfidenceInputError("unavailable evidence must have score 0")
    if state == "FAILED" and numeric != 0:
        raise ConfidenceInputError("failed evidence must have score 0")
    if state == "MATCHED" and numeric < min_evidence_threshold:
        raise ConfidenceInputError("matched evidence is below the configured threshold")
    if state == "WEAK" and not 0 < numeric < min_evidence_threshold:
        raise ConfidenceInputError("weak evidence score contradicts its state")
    source_text = evidence.get("source_text")
    page_number = evidence.get("page_number")
    section_name = evidence.get("section_name")
    page_corrected = evidence.get("page_corrected")
    failure_code = evidence.get("failure_code")
    if "page_corrected" in evidence and not (
        isinstance(page_corrected, bool)
        or (type(page_corrected) is int and page_corrected in (0, 1))
    ):
        raise ConfidenceInputError("page_corrected must be boolean")
    if failure_code is not None and not isinstance(failure_code, str):
        raise ConfidenceInputError("evidence failure code must be text or null")
    if state in {"MATCHED", "WEAK"}:
        if not isinstance(source_text, str) or not source_text.strip():
            raise ConfidenceInputError("matched evidence requires source text")
        if (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or page_number < 1
        ):
            raise ConfidenceInputError("matched evidence requires a valid page")
    elif source_text != "" or page_number is not None:
        raise ConfidenceInputError("unmatched evidence cannot contain a passage")
    if section_name is not None and not isinstance(section_name, str):
        raise ConfidenceInputError("evidence section must be text or null")
    return state, numeric if state == "MATCHED" else 0.0


def route_for_review(
    result: ConfidenceResult, evidence_state: str
) -> ConfidenceResult:
    """Apply evidence and score routing independently from the numeric score."""
    reasons: list[str] = []
    if evidence_state == "UNAVAILABLE":
        reasons.append("evidence_unavailable")
    elif evidence_state == "FAILED":
        reasons.append("evidence_mapping_failed")
    elif evidence_state == "WEAK":
        reasons.append("evidence_weak")
    if result.level == "LOW":
        reasons.append("low_confidence_score")
    return ConfidenceResult(
        score=result.score,
        level=result.level,
        review_required=bool(reasons),
        signals=result.signals,
        review_reasons=reasons,
    )
