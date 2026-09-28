"""Orchestration for PDF, section detection, and the AI extraction checkpoint."""

from __future__ import annotations

from dataclasses import asdict
import json
import logging
from pathlib import Path
import sqlite3
from pydantic import ValidationError

from app.core.config import get_settings
from app.database.connection import connect_database
from app.database.repository import (
    get_paper,
    get_paper_pages,
    get_paper_sections,
    get_extraction_groups,
    replace_extraction_group_results,
    save_pages_and_status,
    save_extraction_group,
    save_sections_and_status,
    set_paper_status,
)
from app.services.pdf_processor import (
    ExtractedPage,
    PdfProcessingError,
    extract_pdf_pages,
)
from app.services.section_detector import detect_sections
from app.schemas.extraction import GROUP_MODELS
from app.services.ai_extraction import AIExtractionService, GROUPS, GroupContext
from app.services.ai_providers import ProviderAdapter, ProviderError
from app.services.evidence_mapper import (
    EvidenceMapper,
    EvidenceResult,
    MalformedEvidenceSource,
)

logger = logging.getLogger(__name__)


def process_paper_text(
    paper_id: int,
    database_path: Path,
    upload_directory: Path,
    provider: ProviderAdapter | None = None,
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

        # TEXT_EXTRACTED is committed above before section detection starts, so
        # a detector or section-write failure cannot discard successful pages.
        try:
            set_paper_status(connection, paper_id, "DETECTING_SECTIONS")
            stored_pages = get_paper_pages(connection, paper_id)
            sections = detect_sections(
                [
                    ExtractedPage(
                        page_number=row["page_number"], text=row["text"]
                    )
                    for row in stored_pages
                ]
            )
            save_sections_and_status(
                connection,
                paper_id,
                (
                    (
                        section.section_name,
                        section.start_page,
                        section.end_page,
                        section.content,
                    )
                    for section in sections
                ),
            )
            logger.info(
                "SECTION_DETECTION_COMPLETED",
                extra={"paper_id": paper_id, "sections_found": len(sections)},
            )
        except Exception:
            connection.rollback()
            logger.exception(
                "SECTION_DETECTION_FAILED", extra={"paper_id": paper_id}
            )
            try:
                set_paper_status(connection, paper_id, "TEXT_EXTRACTED")
            except sqlite3.Error:
                logger.exception(
                    "SECTION_FAILURE_STATE_WRITE_FAILED",
                    extra={"paper_id": paper_id},
                )
            return

        try:
            _extract_paper_groups(connection, paper_id, provider)
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
                    "PAPER_FAILURE_STATE_WRITE_FAILED", extra={"paper_id": paper_id}
                )
            return

        current_paper = get_paper(connection, paper_id)
        if current_paper is not None and current_paper["status"] == "VALIDATING":
            try:
                _map_paper_evidence(connection, paper_id)
            except sqlite3.Error:
                connection.rollback()
                logger.exception(
                    "EVIDENCE_PERSISTENCE_FAILED", extra={"paper_id": paper_id}
                )
                try:
                    set_paper_status(
                        connection,
                        paper_id,
                        "FAILED",
                        "evidence_persistence_failed",
                    )
                except sqlite3.Error:
                    logger.exception(
                        "PAPER_FAILURE_STATE_WRITE_FAILED",
                        extra={"paper_id": paper_id},
                    )
    finally:
        connection.close()


def _extract_paper_groups(
    connection: sqlite3.Connection, paper_id: int, provider: ProviderAdapter | None
) -> None:
    """Validate each structured response before writing its group checkpoint."""
    settings = get_settings()
    pages = {
        row["page_number"]: row["text"]
        for row in get_paper_pages(connection, paper_id)
    }
    sections = [dict(row) for row in get_paper_sections(connection, paper_id)]
    service = AIExtractionService(settings, provider)
    set_paper_status(connection, paper_id, "EXTRACTING_AI")
    failures: dict[str, str] = {}

    for group in GROUPS:
        context = service.context_for_group(group, pages, sections)
        try:
            raw, context = service.extract_group(group, pages, sections)
            validated = GROUP_MODELS[group].model_validate(raw, strict=True)
            save_extraction_group(
                connection,
                paper_id,
                group,
                "SUCCEEDED",
                validated.model_dump_json(),
                context.section_detected,
                context.truncated,
            )
            logger.info(
                "AI_EXTRACTION_GROUP_COMPLETED",
                extra={
                    "paper_id": paper_id,
                    "group": group,
                    "section_detected": context.section_detected,
                    "truncated": context.truncated,
                },
            )
        except ProviderError as exc:
            failures[group] = exc.category
            _save_failed_group(connection, paper_id, group, exc.category, context)
        except ValidationError:
            failures[group] = "validation_failed"
            _save_failed_group(
                connection, paper_id, group, "validation_failed", context
            )
            logger.warning(
                "VALIDATION_FAILED", extra={"paper_id": paper_id, "group": group}
            )
        except Exception:
            failures[group] = "unexpected_extraction_error"
            _save_failed_group(connection, paper_id, group, failures[group], context)
            logger.exception(
                "AI_EXTRACTION_FAILED", extra={"paper_id": paper_id, "group": group}
            )

    if "metadata" in failures:
        set_paper_status(
            connection,
            paper_id,
            "FAILED",
            f"ai_extraction_failed:metadata:{failures['metadata']}",
        )
        logger.error(
            "AI_EXTRACTION_FAILED",
            extra={"paper_id": paper_id, "group": "metadata", "partial": True},
        )
    elif failures:
        set_paper_status(connection, paper_id, "VALIDATING", "partial_ai_extraction")
        logger.info(
            "AI_EXTRACTION_COMPLETED",
            extra={"paper_id": paper_id, "partial": True},
        )
    else:
        set_paper_status(connection, paper_id, "VALIDATING")
        logger.info(
            "AI_EXTRACTION_COMPLETED",
            extra={"paper_id": paper_id, "partial": False},
        )


def _save_failed_group(
    connection: sqlite3.Connection,
    paper_id: int,
    group: str,
    failure_code: str,
    context: GroupContext,
) -> None:
    save_extraction_group(
        connection,
        paper_id,
        group,
        "FAILED",
        None,
        context.section_detected,
        context.truncated,
        failure_code,
    )
    logger.error(
        "AI_EXTRACTION_FAILED",
        extra={"paper_id": paper_id, "group": group, "failure_reason": failure_code},
    )


def _map_paper_evidence(
    connection: sqlite3.Connection, paper_id: int
) -> None:
    """Materialize validated claims and map each against stored page text."""
    settings = get_settings()
    pages = {
        row["page_number"]: row["text"]
        for row in get_paper_pages(connection, paper_id)
    }
    sections = [dict(row) for row in get_paper_sections(connection, paper_id)]
    mapper = EvidenceMapper(settings.min_evidence_threshold)
    groups = get_extraction_groups(connection, paper_id)
    previous = get_paper(connection, paper_id)
    previous_failure = previous["failure_reason"] if previous is not None else None
    set_paper_status(connection, paper_id, "MAPPING_EVIDENCE")
    partial_mapping = False

    for group_row in groups:
        if group_row["status"] != "SUCCEEDED":
            continue
        group_name = group_row["group_name"]
        model = GROUP_MODELS.get(group_name)
        if model is None:
            partial_mapping = True
            logger.error(
                "EVIDENCE_MAPPING_FAILED",
                extra={"paper_id": paper_id, "group": group_name,
                       "failure_reason": "unknown_extraction_group"},
            )
            continue
        try:
            payload = model.model_validate(
                json.loads(group_row["validated_payload"]), strict=True
            )
        except (json.JSONDecodeError, ValidationError, TypeError):
            partial_mapping = True
            logger.exception(
                "EVIDENCE_MAPPING_FAILED",
                extra={"paper_id": paper_id, "group": group_name,
                       "failure_reason": "malformed_extraction"},
            )
            continue

        items: list[dict[str, object]] = []
        for field_name in model.model_fields:
            value = getattr(payload, field_name)
            claims = enumerate(value) if isinstance(value, list) else [(0, value)]
            for item_index, claim in claims:
                if claim.value is None:
                    continue
                try:
                    evidence = mapper.map_source(
                        claim.source_text, claim.page, pages, sections
                    )
                except MalformedEvidenceSource:
                    evidence = EvidenceResult(
                        page_number=None,
                        section_name=None,
                        source_text="",
                        evidence_score=0.0,
                        page_corrected=False,
                        match_status="FAILED",
                        failure_code="malformed_source",
                    )
                    partial_mapping = True
                    logger.warning(
                        "EVIDENCE_MAPPING_FAILED",
                        extra={"paper_id": paper_id, "group": group_name,
                               "field_name": field_name,
                               "failure_reason": "malformed_source"},
                    )
                if evidence.match_status == "UNAVAILABLE":
                    logger.info(
                        "EVIDENCE_MAPPED",
                        extra={"paper_id": paper_id, "group": group_name,
                               "field_name": field_name, "matched": False,
                               "failure_reason": evidence.failure_code},
                    )
                else:
                    logger.info(
                        "EVIDENCE_MAPPED",
                        extra={"paper_id": paper_id, "group": group_name,
                               "field_name": field_name, "matched": True,
                               "match_status": evidence.match_status},
                    )
                items.append(
                    {
                        "field_name": field_name,
                        "item_index": item_index,
                        "field_value": claim.value,
                        "proposed_source_text": claim.source_text,
                        "proposed_page": claim.page,
                        "proposed_section": claim.section,
                        "section_detected": bool(group_row["section_detected"]),
                        "evidence": asdict(evidence),
                    }
                )
        replace_extraction_group_results(
            connection, paper_id, group_name, items
        )

    if previous_failure == "partial_ai_extraction":
        failure_reason = "partial_ai_extraction"
    elif partial_mapping:
        failure_reason = "partial_evidence_mapping"
    else:
        failure_reason = None
    set_paper_status(
        connection, paper_id, "SCORING_CONFIDENCE", failure_reason
    )
