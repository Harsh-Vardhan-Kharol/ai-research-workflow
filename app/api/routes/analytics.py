"""Live deterministic research analytics routes."""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter

from app.api.errors import ApiError
from app.core.config import get_settings
from app.database.connection import connect_database
from app.schemas.comparison import ComparisonRequest, ComparisonResponse
from app.schemas.insights import InsightResponse
from app.services.comparison_service import ComparisonSelectionError, compare_papers
from app.services.ai_providers import ProviderError
from app.services.insight_service import (
    InsightService, InsightValidationError, build_insight_input,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.post("/compare", response_model=ComparisonResponse)
def compare_selected_papers(payload: ComparisonRequest) -> ComparisonResponse:
    """Compare READY papers from persisted structured extraction records."""
    connection = connect_database()
    try:
        result = compare_papers(connection, payload.paper_ids)
        return ComparisonResponse(**result)
    except ComparisonSelectionError as exc:
        logger.info("PAPER_COMPARISON_REJECTED", extra={"reason": exc.code})
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    except sqlite3.Error as exc:
        logger.exception("PAPER_COMPARISON_DATABASE_FAILED")
        raise ApiError(500, "DATABASE_ERROR", "Comparison could not be completed.") from exc
    finally:
        connection.close()


@router.post("/insights", response_model=InsightResponse)
def generate_selected_paper_insights(payload: ComparisonRequest) -> InsightResponse:
    """Interpret deterministic comparison results without reading paper text."""
    connection = connect_database()
    try:
        comparison = compare_papers(connection, payload.paper_ids)
    except ComparisonSelectionError as exc:
        logger.info("PAPER_INSIGHTS_REJECTED", extra={"reason": exc.code})
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    except sqlite3.Error as exc:
        logger.exception("PAPER_INSIGHTS_COMPARISON_FAILED")
        raise ApiError(500, "DATABASE_ERROR", "Insights could not be prepared.") from exc
    finally:
        connection.close()

    try:
        package = build_insight_input(comparison)
        insights = InsightService(get_settings()).generate(package)
        return InsightResponse(insights=insights)
    except ProviderError as exc:
        logger.warning("RESEARCH_INSIGHTS_PROVIDER_FAILED", extra={"category": exc.category})
        if exc.category == "timeout":
            raise ApiError(504, "INSIGHT_TIMEOUT", "The insight provider timed out.") from exc
        if exc.category == "configuration_error":
            raise ApiError(503, "INSIGHT_PROVIDER_UNAVAILABLE", "AI insights are unavailable because no provider is configured.") from exc
        if exc.category in {"malformed_response", "unexpected_response", "empty_response"}:
            raise ApiError(502, "INVALID_INSIGHT_OUTPUT", "The insight provider returned malformed output.") from exc
        raise ApiError(503, "INSIGHT_PROVIDER_UNAVAILABLE", "The insight provider is unavailable.") from exc
    except InsightValidationError as exc:
        logger.warning("RESEARCH_INSIGHTS_INVALID", extra={"reason": str(exc)})
        raise ApiError(502, "INVALID_INSIGHT_OUTPUT", "The insight provider returned unsupported or malformed output.") from exc
    except sqlite3.Error as exc:
        # Covers no database work after comparison; retained as a safe boundary
        # if package construction changes to use repository results later.
        logger.exception("RESEARCH_INSIGHTS_DATABASE_FAILED")
        raise ApiError(500, "DATABASE_ERROR", "Insights could not be completed.") from exc
