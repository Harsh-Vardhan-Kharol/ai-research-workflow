"""Environment-backed application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

AIProvider = Literal["hosted", "mock"]


@dataclass(frozen=True, slots=True)
class Settings:
    ai_provider: AIProvider
    ai_api_key: str | None
    ai_model_name: str | None
    ai_base_url: str
    ai_timeout_seconds: int
    database_path: Path
    max_upload_size_mb: int
    max_ai_retries: int
    max_extraction_chars: int
    min_evidence_threshold: float
    gap_concentration_threshold: float
    gap_sparse_threshold: float
    log_level: str


def _positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def get_settings() -> Settings:
    """Load `.env` without overriding explicitly supplied environment values."""
    load_dotenv(override=False)

    provider = os.getenv("AI_PROVIDER", "hosted").strip().lower()
    if provider not in {"hosted", "mock"}:
        raise ValueError("AI_PROVIDER must be hosted or mock")

    threshold_raw = os.getenv("MIN_EVIDENCE_THRESHOLD", "0.35")
    try:
        threshold = float(threshold_raw)
    except ValueError as exc:
        raise ValueError("MIN_EVIDENCE_THRESHOLD must be a number") from exc
    if not 0 <= threshold <= 1:
        raise ValueError("MIN_EVIDENCE_THRESHOLD must be between 0 and 1")

    def proportion(name: str, default: str) -> float:
        try:
            value = float(os.getenv(name, default))
        except ValueError as exc:
            raise ValueError(f"{name} must be a number") from exc
        if not 0 < value <= 1:
            raise ValueError(f"{name} must be greater than 0 and at most 1")
        return value

    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("LOG_LEVEL must be a standard Python logging level")

    database_path = Path(os.getenv("DATABASE_PATH", "./data/researchflow.db"))
    return Settings(
        ai_provider=provider,  # type: ignore[arg-type]
        ai_api_key=os.getenv("AI_API_KEY") or None,
        ai_model_name=os.getenv("AI_MODEL_NAME") or None,
        ai_base_url=os.getenv("AI_BASE_URL", "").strip(),
        ai_timeout_seconds=_positive_int("AI_TIMEOUT_SECONDS", 30),
        database_path=database_path,
        max_upload_size_mb=_positive_int("MAX_UPLOAD_SIZE_MB", 25),
        max_ai_retries=_positive_int("MAX_AI_RETRIES", 2),
        max_extraction_chars=_positive_int("MAX_EXTRACTION_CHARS", 12000),
        min_evidence_threshold=threshold,
        gap_concentration_threshold=proportion("GAP_CONCENTRATION_THRESHOLD", "0.70"),
        gap_sparse_threshold=proportion("GAP_SPARSE_THRESHOLD", "0.50"),
        log_level=log_level,
    )
