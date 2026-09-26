"""Orchestration for the deterministic PDF text-extraction stage."""

from __future__ import annotations

import logging
from pathlib import Path
import sqlite3

from app.database.connection import connect_database
from app.database.repository import get_paper, save_pages_and_status, set_paper_status
from app.services.pdf_processor import PdfProcessingError, extract_pdf_pages

logger = logging.getLogger(__name__)


def process_paper_text(
    paper_id: int, database_path: Path, upload_directory: Path
) -> None:
    """Extract and persist a paper's page text; failures update its state."""
    connection = connect_database(database_path)
    try:
        paper = get_paper(connection, paper_id)
        if paper is None:
            logger.error(
                "PROCESSING_FAILED",
                extra={"paper_id": paper_id, "failure_reason": "paper_not_found"},
            )
            return

        pdf_path = upload_directory / f"{paper['file_hash']}.pdf"
        logger.info("PDF_EXTRACTION_STARTED", extra={"paper_id": paper_id})
        try:
            if not pdf_path.is_file():
                raise OSError("Stored PDF is missing")
            pages = extract_pdf_pages(pdf_path)
            save_pages_and_status(
                connection,
                paper_id,
                ((page.page_number, page.text) for page in pages),
            )
        except PdfProcessingError as exc:
            set_paper_status(connection, paper_id, "FAILED", exc.failure_reason)
            logger.error(
                "PROCESSING_FAILED",
                extra={"paper_id": paper_id, "failure_reason": exc.failure_reason},
            )
            return
        except OSError as exc:
            set_paper_status(connection, paper_id, "FAILED", "stored_pdf_missing")
            logger.error(
                "PROCESSING_FAILED",
                extra={"paper_id": paper_id, "failure_reason": "stored_pdf_missing"},
            )
            logger.debug("Stored PDF access failed", exc_info=exc)
            return
        except sqlite3.Error:
            connection.rollback()
            logger.exception(
                "PROCESSING_FAILED",
                extra={"paper_id": paper_id, "failure_reason": "database_error"},
            )
            try:
                set_paper_status(connection, paper_id, "FAILED", "database_error")
            except sqlite3.Error:
                logger.exception(
                    "PAPER_FAILURE_STATE_WRITE_FAILED",
                    extra={"paper_id": paper_id},
                )
            return

        logger.info(
            "PDF_EXTRACTION_COMPLETED",
            extra={"paper_id": paper_id, "page_count": len(pages)},
        )
    finally:
        connection.close()
