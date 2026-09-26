"""PDF upload validation, safe staging, hashing, and page-aware extraction."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile

import pymupdf
from fastapi import UploadFile


CHUNK_SIZE = 64 * 1024
PDF_SIGNATURE = b"%PDF-"
MIN_EXTRACTABLE_CHARACTERS = 20


class UploadRejected(ValueError):
    """An upload failed a client-input validation check."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class PdfProcessingError(ValueError):
    """A stored PDF could not produce usable page text."""

    def __init__(self, failure_reason: str, message: str) -> None:
        super().__init__(message)
        self.failure_reason = failure_reason
        self.message = message


@dataclass(frozen=True, slots=True)
class StagedPdf:
    path: Path
    file_hash: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    page_number: int
    text: str


async def stage_pdf_upload(
    upload: UploadFile,
    upload_directory: Path,
    max_size_bytes: int,
) -> StagedPdf:
    """Validate and stream an upload to a generated temporary file."""
    filename = upload.filename or ""
    if Path(filename).suffix.lower() != ".pdf":
        raise UploadRejected(
            "INVALID_FILE_TYPE", "Only PDF files are supported.", 400
        )

    media_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    if media_type != "application/pdf":
        raise UploadRejected(
            "INVALID_FILE_TYPE", "Only PDF files are supported.", 400
        )
    if max_size_bytes <= 0:
        raise ValueError("max_size_bytes must be positive")

    upload_directory.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".upload-", suffix=".tmp", dir=upload_directory
    )
    temporary_path = Path(temporary_name)
    digest = hashlib.sha256()
    size_bytes = 0
    prefix = bytearray()

    try:
        with os.fdopen(file_descriptor, "wb") as destination:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > max_size_bytes:
                    raise UploadRejected(
                        "FILE_TOO_LARGE",
                        f"File exceeds the {max_size_bytes // (1024 * 1024)}MB limit.",
                        413,
                    )
                if len(prefix) < len(PDF_SIGNATURE):
                    prefix.extend(chunk[: len(PDF_SIGNATURE) - len(prefix)])
                    if (
                        len(prefix) == len(PDF_SIGNATURE)
                        and bytes(prefix) != PDF_SIGNATURE
                    ):
                        raise UploadRejected(
                            "INVALID_FILE_TYPE", "Only PDF files are supported.", 400
                        )
                digest.update(chunk)
                destination.write(chunk)

        if size_bytes == 0 or bytes(prefix) != PDF_SIGNATURE:
            raise UploadRejected(
                "INVALID_PDF", "The uploaded file is not a valid PDF.", 400
            )
        return StagedPdf(temporary_path, digest.hexdigest(), size_bytes)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def extract_pdf_pages(pdf_path: str | Path) -> list[ExtractedPage]:
    """Extract text without flattening page boundaries or page numbers."""
    try:
        document = pymupdf.open(pdf_path)
    except Exception as exc:
        raise PdfProcessingError(
            "corrupted_pdf", "This file could not be opened as a valid PDF."
        ) from exc

    try:
        if document.page_count == 0:
            raise PdfProcessingError("empty_pdf", "This PDF contains no pages.")
        pages: list[ExtractedPage] = []
        try:
            for index, page in enumerate(document, start=1):
                pages.append(ExtractedPage(page_number=index, text=page.get_text("text")))
        except Exception as exc:
            raise PdfProcessingError(
                "corrupted_pdf", "This file could not be opened as a valid PDF."
            ) from exc
    finally:
        document.close()

    visible_characters = sum(
        not character.isspace() for page in pages for character in page.text
    )
    if visible_characters < MIN_EXTRACTABLE_CHARACTERS:
        raise PdfProcessingError(
            "no_extractable_text",
            "No extractable text was found (scanned PDFs are not supported).",
        )
    return pages
