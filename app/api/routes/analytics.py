"""Live deterministic research analytics routes."""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter

from app.api.errors import ApiError
from app.database.connection import connect_database
from app.schemas.comparison import ComparisonRequest, ComparisonResponse
from app.services.comparison_service import ComparisonSelectionError, compare_papers

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
