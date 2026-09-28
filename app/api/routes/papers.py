"""Paper upload and page-text processing API routes."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3

from fastapi import APIRouter, BackgroundTasks, File, UploadFile

from app.api.errors import ApiError
from app.core.config import get_settings
from app.database.connection import connect_database
from app.database.repository import (
    create_paper,
    get_extraction_with_evidence,
    find_paper_by_hash,
    get_extractions_for_paper,
    get_extraction_groups,
    get_paper,
    initialize_schema,
    set_paper_status,
)
from app.schemas.papers import (
    ExtractionEvidenceResponse,
    EvidenceSummary,
    PaperExtractionsResponse,
    PaperExtractionGroupsResponse,
    PaperProcessResponse,
    PaperStatusResponse,
    PaperUploadResponse,
)
from app.services.paper_processing import process_paper_text
from app.services.pdf_processor import UploadRejected, stage_pdf_upload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/papers", tags=["papers"])
evidence_router = APIRouter(prefix="/api/v1", tags=["evidence"])


def _upload_directory(database_path: Path) -> Path:
    return database_path.parent / "uploads"


@router.post("/upload", status_code=201, response_model=PaperUploadResponse)
async def upload_paper(file: UploadFile = File(...)) -> PaperUploadResponse:
    settings = get_settings()
    upload_directory = _upload_directory(settings.database_path)
    try:
        staged = await stage_pdf_upload(
            file,
            upload_directory,
            settings.max_upload_size_mb * 1024 * 1024,
        )
    except UploadRejected as exc:
        logger.warning(
            "UPLOAD_REJECTED", extra={"reason": exc.code, "file_name": file.filename}
        )
        raise ApiError(exc.status_code, exc.code, exc.message) from exc
    except OSError as exc:
        logger.exception("PAPER_UPLOAD_STORAGE_FAILED")
        raise ApiError(
            500, "STORAGE_ERROR", "The uploaded file could not be staged."
        ) from exc

    connection = None
    stored_path: Path | None = None
    keep_stored_file = False
    try:
        connection = connect_database(settings.database_path)
        initialize_schema(connection)
        existing = find_paper_by_hash(connection, staged.file_hash)
        if existing is not None:
            staged.path.unlink(missing_ok=True)
            logger.info(
                "UPLOAD_REJECTED",
                extra={"reason": "duplicate", "existing_paper_id": existing["id"]},
            )
            raise ApiError(
                409,
                "DUPLICATE_PAPER",
                f"This file has already been uploaded (paper #{existing['id']}).",
                existing_paper_id=existing["id"],
            )

        stored_path = upload_directory / f"{staged.file_hash}.pdf"
        staged.path.replace(stored_path)
        paper_id = create_paper(
            connection, file.filename or "upload.pdf", staged.file_hash
        )
        keep_stored_file = True
        logger.info(
            "PAPER_UPLOADED",
            extra={
                "paper_id": paper_id,
                "file_name": file.filename,
                "byte_count": staged.size_bytes,
            },
        )
        return PaperUploadResponse(
            id=paper_id,
            status="UPLOADED",
            file_name=file.filename or "upload.pdf",
        )
    except ApiError:
        raise
    except sqlite3.IntegrityError as exc:
        existing = (
            find_paper_by_hash(connection, staged.file_hash)
            if connection is not None
            else None
        )
        if existing is not None:
            raise ApiError(
                409,
                "DUPLICATE_PAPER",
                f"This file has already been uploaded (paper #{existing['id']}).",
                existing_paper_id=existing["id"],
            ) from exc
        raise ApiError(
            500,
            "DATABASE_ERROR",
            "A database error occurred while saving the paper.",
        ) from exc
    except sqlite3.Error as exc:
        logger.exception("PAPER_UPLOAD_DATABASE_FAILED")
        raise ApiError(
            500,
            "DATABASE_ERROR",
            "A database error occurred while saving the paper.",
        ) from exc
    except OSError as exc:
        logger.exception("PAPER_UPLOAD_STORAGE_FAILED")
        raise ApiError(
            500, "STORAGE_ERROR", "The uploaded file could not be stored."
        ) from exc
    finally:
        staged.path.unlink(missing_ok=True)
        if stored_path is not None and not keep_stored_file:
            stored_path.unlink(missing_ok=True)
        if connection is not None:
            connection.close()
        await file.close()


@router.post(
    "/{paper_id}/process", status_code=202, response_model=PaperProcessResponse
)
def process_paper(
    paper_id: int, background_tasks: BackgroundTasks
) -> PaperProcessResponse:
    settings = get_settings()
    connection = connect_database(settings.database_path)
    try:
        paper = get_paper(connection, paper_id)
        if paper is None:
            raise ApiError(404, "PAPER_NOT_FOUND", "Paper not found.")
        retryable_partial = (
            paper["status"] == "VALIDATING"
            and paper["failure_reason"] == "partial_ai_extraction"
        ) or (
            paper["status"] == "SCORING_CONFIDENCE"
            and paper["failure_reason"]
            in {"partial_ai_extraction", "partial_evidence_mapping"}
        )
        if paper["status"] in {
            "EXTRACTING_TEXT",
            "TEXT_EXTRACTED",
            "DETECTING_SECTIONS",
            "EXTRACTING_AI",
            "VALIDATING",
            "MAPPING_EVIDENCE",
            "SCORING_CONFIDENCE",
            "READY",
        } and not retryable_partial:
            raise ApiError(
                409,
                "PROCESSING_CONFLICT",
                f"Paper is already {paper['status']}.",
                current_status=paper["status"],
            )
        set_paper_status(connection, paper_id, "EXTRACTING_TEXT")
    except sqlite3.Error as exc:
        logger.exception(
            "PAPER_PROCESSING_DATABASE_FAILED", extra={"paper_id": paper_id}
        )
        raise ApiError(
            500,
            "DATABASE_ERROR",
            "A database error occurred while processing the paper.",
        ) from exc
    finally:
        connection.close()

    upload_directory = _upload_directory(settings.database_path)
    background_tasks.add_task(
        process_paper_text,
        paper_id,
        settings.database_path,
        upload_directory,
    )
    return PaperProcessResponse(status="EXTRACTING_TEXT")


@router.get("/{paper_id}/status", response_model=PaperStatusResponse)
def get_paper_status(paper_id: int) -> PaperStatusResponse:
    connection = connect_database()
    try:
        paper = get_paper(connection, paper_id)
        if paper is None:
            raise ApiError(404, "PAPER_NOT_FOUND", "Paper not found.")
        return PaperStatusResponse(
            status=paper["status"], failure_reason=paper["failure_reason"]
        )
    finally:
        connection.close()


@router.get(
    "/{paper_id}/extraction-groups", response_model=PaperExtractionGroupsResponse
)
def get_paper_extraction_groups(paper_id: int) -> PaperExtractionGroupsResponse:
    """Return only validated payloads and safe per-group failure metadata."""
    connection = connect_database()
    try:
        paper = get_paper(connection, paper_id)
        if paper is None:
            raise ApiError(404, "PAPER_NOT_FOUND", "Paper not found.")
        groups = []
        for row in get_extraction_groups(connection, paper_id):
            groups.append(
                {
                    "group_name": row["group_name"],
                    "status": row["status"],
                    "validated_payload": (
                        json.loads(row["validated_payload"])
                        if row["validated_payload"] is not None
                        else None
                    ),
                    "section_detected": bool(row["section_detected"]),
                    "truncated": bool(row["truncated"]),
                    "failure_code": row["failure_code"],
                }
            )
        return PaperExtractionGroupsResponse(paper_id=paper_id, groups=groups)
    finally:
        connection.close()


@router.get("/{paper_id}/extractions", response_model=PaperExtractionsResponse)
def get_paper_extractions(paper_id: int) -> PaperExtractionsResponse:
    """Return claims separately from their proposed and matched sources."""
    connection = connect_database()
    try:
        if get_paper(connection, paper_id) is None:
            raise ApiError(404, "PAPER_NOT_FOUND", "Paper not found.")
        extractions = []
        for row in get_extractions_for_paper(connection, paper_id):
            joined = get_extraction_with_evidence(connection, row["id"])
            evidence = None
            if joined is not None and joined["match_status"] is not None:
                evidence = EvidenceSummary(
                    proposed_source_text=joined["proposed_source_text"],
                    proposed_page=joined["proposed_page"],
                    proposed_section=joined["proposed_section"],
                    page_number=joined["page_number"],
                    section_name=joined["section_name"],
                    matched_source_text=joined["verified_source_text"],
                    evidence_score=joined["evidence_score"],
                    page_corrected=bool(joined["page_corrected"]),
                    match_status=joined["match_status"],
                    failure_code=joined["failure_code"],
                )
            extractions.append(
                {
                    **dict(row),
                    "section_detected": bool(row["section_detected"]),
                    "evidence": evidence,
                }
            )
        return PaperExtractionsResponse(paper_id=paper_id, extractions=extractions)
    finally:
        connection.close()


@evidence_router.get(
    "/extractions/{extraction_id}/evidence",
    response_model=ExtractionEvidenceResponse,
)
def get_extraction_evidence(extraction_id: int) -> ExtractionEvidenceResponse:
    """Return the proposal and independent page-text match side by side."""
    connection = connect_database()
    try:
        row = get_extraction_with_evidence(connection, extraction_id)
        if row is None or row["match_status"] is None:
            raise ApiError(404, "EVIDENCE_NOT_FOUND", "Evidence was not found.")
        return ExtractionEvidenceResponse(
            extraction_id=row["id"],
            field_name=row["field_name"],
            field_value=row["field_value"],
            proposed_source_text=row["proposed_source_text"],
            proposed_page=row["proposed_page"],
            proposed_section=row["proposed_section"],
            page_number=row["page_number"],
            section_name=row["section_name"],
            matched_source_text=row["verified_source_text"],
            evidence_score=row["evidence_score"],
            page_corrected=bool(row["page_corrected"]),
            match_status=row["match_status"],
            failure_code=row["failure_code"],
        )
    finally:
        connection.close()
