"""Paper upload and page-text processing API routes."""

from __future__ import annotations

import logging
from pathlib import Path
import sqlite3

from fastapi import APIRouter, BackgroundTasks, File, UploadFile

from app.api.errors import ApiError
from app.core.config import get_settings
from app.database.connection import connect_database
from app.database.repository import (
    create_paper,
    find_paper_by_hash,
    get_paper,
    initialize_schema,
    set_paper_status,
)
from app.schemas.papers import (
    PaperProcessResponse,
    PaperStatusResponse,
    PaperUploadResponse,
)
from app.services.paper_processing import process_paper_text
from app.services.pdf_processor import UploadRejected, stage_pdf_upload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/papers", tags=["papers"])


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
        raise ApiError(500, "STORAGE_ERROR", "The uploaded file could not be staged.") from exc

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
        paper_id = create_paper(connection, file.filename or "upload.pdf", staged.file_hash)
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
        raise ApiError(500, "STORAGE_ERROR", "The uploaded file could not be stored.") from exc
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
        if paper["status"] in {
            "EXTRACTING_TEXT",
            "TEXT_EXTRACTED",
            "DETECTING_SECTIONS",
            "EXTRACTING_AI",
            "VALIDATING",
            "MAPPING_EVIDENCE",
            "SCORING_CONFIDENCE",
            "READY",
        }:
            raise ApiError(
                409,
                "PROCESSING_CONFLICT",
                f"Paper is already {paper['status']}.",
                current_status=paper["status"],
            )
        set_paper_status(connection, paper_id, "EXTRACTING_TEXT")
    except sqlite3.Error as exc:
        logger.exception("PAPER_PROCESSING_DATABASE_FAILED", extra={"paper_id": paper_id})
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
