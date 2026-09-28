"""Unit and API integration tests for PDF upload and page extraction."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from io import BytesIO

import pymupdf
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers, UploadFile

import app.main as main_module
from app.api.routes import papers as papers_routes
from app.core.config import get_settings
from app.database.connection import connect_database
from app.database.repository import (
    get_paper_pages,
    get_paper_sections,
    initialize_schema,
)
from app.services.pdf_processor import (
    PdfProcessingError,
    UploadRejected,
    extract_pdf_pages,
    stage_pdf_upload,
)


def make_pdf(*page_texts: str) -> bytes:
    document = pymupdf.open()
    for text in page_texts:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def make_upload(
    content: bytes,
    filename: str = "paper.pdf",
    content_type: str = "application/pdf",
) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=BytesIO(content),
        headers=Headers({"content-type": content_type}),
    )


def run_stage(upload: UploadFile, directory, max_size: int = 1024 * 1024):
    return asyncio.run(stage_pdf_upload(upload, directory, max_size))


def test_stage_pdf_upload_hashes_and_stages_with_generated_name(tmp_path) -> None:
    content = make_pdf("This page contains enough text to pass the extraction minimum.")

    staged = run_stage(make_upload(content, "../../private/research.pdf"), tmp_path)

    assert staged.file_hash
    assert staged.size_bytes == len(content)
    assert staged.path.parent == tmp_path
    assert "research.pdf" not in staged.path.name
    assert staged.path.read_bytes() == content


def test_upload_rejects_bad_extension_and_mime(tmp_path) -> None:
    with pytest.raises(UploadRejected) as extension_error:
        run_stage(make_upload(b"%PDF-file", "paper.txt"), tmp_path)
    assert extension_error.value.status_code == 400

    with pytest.raises(UploadRejected) as mime_error:
        run_stage(make_upload(b"%PDF-file", content_type="text/plain"), tmp_path)
    assert mime_error.value.code == "INVALID_FILE_TYPE"


def test_upload_rejects_invalid_signature_and_oversized_file(tmp_path) -> None:
    with pytest.raises(UploadRejected) as signature_error:
        run_stage(make_upload(b"not a pdf"), tmp_path)
    assert signature_error.value.code == "INVALID_FILE_TYPE"
    assert list(tmp_path.iterdir()) == []

    with pytest.raises(UploadRejected) as size_error:
        run_stage(make_upload(b"%PDF-" + b"x" * 100), tmp_path, max_size=50)
    assert size_error.value.status_code == 413
    assert list(tmp_path.iterdir()) == []

    with pytest.raises(UploadRejected) as empty_error:
        run_stage(make_upload(b""), tmp_path)
    assert empty_error.value.code == "INVALID_PDF"


def test_page_extraction_preserves_page_numbers_and_text(tmp_path) -> None:
    pdf_path = tmp_path / "valid.pdf"
    pdf_path.write_bytes(
        make_pdf(
            "First page has enough extractable scientific text.",
            "Second page also has enough extractable scientific text.",
        )
    )

    pages = extract_pdf_pages(pdf_path)

    assert [page.page_number for page in pages] == [1, 2]
    assert "First page" in pages[0].text
    assert "Second page" in pages[1].text


def test_page_extraction_reports_corrupted_and_blank_documents(tmp_path) -> None:
    corrupt_path = tmp_path / "corrupt.pdf"
    corrupt_path.write_bytes(b"%PDF-this is not a valid PDF body")
    with pytest.raises(PdfProcessingError) as corrupt_error:
        extract_pdf_pages(corrupt_path)
    assert corrupt_error.value.failure_reason == "corrupted_pdf"

    blank_path = tmp_path / "blank.pdf"
    blank_path.write_bytes(make_pdf(""))
    with pytest.raises(PdfProcessingError) as blank_error:
        extract_pdf_pages(blank_path)
    assert blank_error.value.failure_reason == "no_extractable_text"


def test_page_extraction_reports_zero_page_document(monkeypatch, tmp_path) -> None:
    class EmptyDocument:
        page_count = 0

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "app.services.pdf_processor.pymupdf.open", lambda _: EmptyDocument()
    )
    with pytest.raises(PdfProcessingError) as error:
        extract_pdf_pages(tmp_path / "zero-pages.pdf")
    assert error.value.failure_reason == "empty_pdf"


def test_upload_process_persists_page_text_and_detects_duplicate(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "researchflow.db"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setattr(
        main_module,
        "settings",
        replace(main_module.settings, database_path=database_path),
    )
    monkeypatch.setattr(
        papers_routes,
        "get_settings",
        lambda: replace(get_settings(), database_path=database_path),
    )

    content = make_pdf(
        "1. Introduction\nPage one contains enough text for extraction "
        "and traceability.",
        "RESULTS\nPage two remains a separate source page with its own text.",
    )
    with TestClient(main_module.app) as client:
        invalid_response = client.post(
            "/api/v1/papers/upload",
            files={"file": ("paper.pdf", b"%PDF-invalid", "text/plain")},
        )
        assert invalid_response.status_code == 400
        assert invalid_response.json()["error"]["code"] == "INVALID_FILE_TYPE"

        upload_response = client.post(
            "/api/v1/papers/upload",
            files={"file": ("paper.pdf", content, "application/pdf")},
        )
        assert upload_response.status_code == 201
        paper_id = upload_response.json()["id"]

        duplicate_response = client.post(
            "/api/v1/papers/upload",
            files={"file": ("copy.pdf", content, "application/pdf")},
        )
        assert duplicate_response.status_code == 409
        assert duplicate_response.json()["error"]["existing_paper_id"] == paper_id

        process_response = client.post(f"/api/v1/papers/{paper_id}/process")
        assert process_response.status_code == 202
        assert process_response.json()["status"] == "EXTRACTING_TEXT"
        status_response = client.get(f"/api/v1/papers/{paper_id}/status")
        assert status_response.json() == {
            "status": "SCORING_CONFIDENCE",
            "failure_reason": None,
        }
        extraction_response = client.get(
            f"/api/v1/papers/{paper_id}/extraction-groups"
        )
        assert extraction_response.status_code == 200
        groups = extraction_response.json()["groups"]
        assert len(groups) == 5
        assert all(group["status"] == "SUCCEEDED" for group in groups)
        assert all(group["validated_payload"] is not None for group in groups)
        repeated_process_response = client.post(
            f"/api/v1/papers/{paper_id}/process"
        )
        assert repeated_process_response.status_code == 409
        assert (
            repeated_process_response.json()["error"]["current_status"]
            == "SCORING_CONFIDENCE"
        )

    connection = connect_database(database_path)
    try:
        initialize_schema(connection)
        pages = get_paper_pages(connection, paper_id)
        assert [page["page_number"] for page in pages] == [1, 2]
        assert "Page one" in pages[0]["text"]
        assert "Page two" in pages[1]["text"]
        sections = get_paper_sections(connection, paper_id)
        assert [section["section_name"] for section in sections] == [
            "Introduction",
            "Results",
        ]
        assert sections[0]["start_page"] == 1
        assert sections[0]["end_page"] == 1
        assert "Page one" in sections[0]["content"]
    finally:
        connection.close()


def test_corrupt_pdf_processing_sets_failed_status_and_reason(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "researchflow.db"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setattr(
        main_module,
        "settings",
        replace(main_module.settings, database_path=database_path),
    )
    monkeypatch.setattr(
        papers_routes,
        "get_settings",
        lambda: replace(get_settings(), database_path=database_path),
    )

    with TestClient(main_module.app) as client:
        for filename, content, expected_reason in (
            ("broken.pdf", b"%PDF-invalid body", "corrupted_pdf"),
            ("blank.pdf", make_pdf(""), "no_extractable_text"),
        ):
            upload_response = client.post(
                "/api/v1/papers/upload",
                files={"file": (filename, content, "application/pdf")},
            )
            assert upload_response.status_code == 201
            paper_id = upload_response.json()["id"]
            client.post(f"/api/v1/papers/{paper_id}/process")
            status_response = client.get(f"/api/v1/papers/{paper_id}/status")
            assert status_response.json() == {
                "status": "FAILED",
                "failure_reason": expected_reason,
            }


def test_section_detection_failure_preserves_extracted_page_text(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "researchflow.db"
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setattr(
        main_module,
        "settings",
        replace(main_module.settings, database_path=database_path),
    )
    monkeypatch.setattr(
        papers_routes,
        "get_settings",
        lambda: replace(get_settings(), database_path=database_path),
    )
    monkeypatch.setattr(
        "app.services.paper_processing.detect_sections",
        lambda _: (_ for _ in ()).throw(RuntimeError("detector failure")),
    )

    content = make_pdf(
        "Introduction\nExtractable text remains available after failure."
    )
    with TestClient(main_module.app) as client:
        upload_response = client.post(
            "/api/v1/papers/upload",
            files={"file": ("paper.pdf", content, "application/pdf")},
        )
        paper_id = upload_response.json()["id"]

        process_response = client.post(f"/api/v1/papers/{paper_id}/process")
        assert process_response.status_code == 202
        status_response = client.get(f"/api/v1/papers/{paper_id}/status")
        assert status_response.json() == {
            "status": "TEXT_EXTRACTED",
            "failure_reason": None,
        }

    connection = connect_database(database_path)
    try:
        pages = get_paper_pages(connection, paper_id)
        assert len(pages) == 1
        assert "Extractable text remains available" in pages[0]["text"]
        assert get_paper_sections(connection, paper_id) == []
    finally:
        connection.close()
