"""Response models for PDF ingestion and processing status."""

from __future__ import annotations

from pydantic import BaseModel


class PaperUploadResponse(BaseModel):
    id: int
    status: str
    file_name: str


class PaperProcessResponse(BaseModel):
    status: str


class PaperStatusResponse(BaseModel):
    status: str
    failure_reason: str | None
