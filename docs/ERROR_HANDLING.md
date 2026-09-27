# Error Handling

## Failure-mode matrix

| Failure | Detection | Handling | User message | Log event |
|---|---|---|---|---|
| Invalid file type | Extension/MIME check on upload | Reject before storage | "Only PDF files are supported." | `UPLOAD_REJECTED` (WARNING) |
| Invalid or empty PDF payload | Missing `%PDF-` signature or zero-byte upload | Reject before storage | "The uploaded file is not a valid PDF." | `UPLOAD_REJECTED` (WARNING) |
| Oversized file | Size check before read | Reject before storage | "File exceeds the {N}MB limit." | `UPLOAD_REJECTED` (WARNING) |
| Corrupted PDF | PyMuPDF open() raises | `status = FAILED`, `failure_reason = corrupted_pdf` | "This file could not be opened as a valid PDF." | `PROCESSING_FAILED` (ERROR) |
| Empty PDF | PyMuPDF opens a document with zero pages | `status = FAILED`, `failure_reason = empty_pdf` | "This PDF contains no pages." | `PROCESSING_FAILED` (ERROR) |
| Stored PDF missing | Content-addressed PDF file is absent at processing time | `status = FAILED`, `failure_reason = stored_pdf_missing` | "The stored PDF is unavailable for processing." | `PROCESSING_FAILED` (ERROR) |
| Scanned/no extractable text | Extracted text near-empty across all pages | `status = FAILED`, `failure_reason = no_extractable_text` | "No extractable text was found (scanned PDFs are not supported)." | `PROCESSING_FAILED` (ERROR) |
| Section detection finds nothing | No standalone known headings matched | Not a failure — create no section rows; later extraction falls back to whole-document text and flags `section_detected=false` | No user-facing error | `SECTION_DETECTION_COMPLETED` (INFO, `sections_found=0`) |
| Section detection or section persistence fails | Detector raises or section transaction fails | Preserve committed page text and return paper status to `TEXT_EXTRACTED`; do not fail PDF extraction | No user-facing error | `SECTION_DETECTION_FAILED` (ERROR) |
| LLM timeout | Adapter call exceeds timeout | Retry up to `MAX_AI_RETRIES`, then fail just that extraction group | "Some fields could not be extracted; you can retry with Reanalyze." | `AI_EXTRACTION_FAILED` (ERROR, per group) |
| LLM rate limit | Provider 429 | Exponential backoff, max 2 retries, then fail that group | same as above | `AI_EXTRACTION_FAILED` (ERROR) |
| Invalid JSON from LLM | JSON parse fails | One repair retry with parse error included, then fail that group | same as above | `VALIDATION_FAILED` (ERROR) |
| Schema validation failure (field-level) | Pydantic raises on a field | Drop that field only, keep the rest of the group | (no user-facing error unless all fields in a group fail) | `VALIDATION_FAILED` (WARNING, field-level) |
| Evidence extraction failure | No page/section identifiable | Store extraction with `evidence_score=0`, no evidence row or a null-page evidence row | Evidence panel shows "no evidence available" | `EVIDENCE_MAPPED` (INFO, `matched=false`) |
| Database errors | Exception on write | Roll back the transaction for that group only; do not corrupt already-committed groups | "A database error occurred while saving results." | `PROCESSING_FAILED` (ERROR) |
| Duplicate paper (same hash) | Hash check on upload | 409, do not re-process | "This file has already been uploaded (paper #{id})." | `UPLOAD_REJECTED` (INFO) |
| Partial batch failure (some extraction groups succeed, others fail) | Per-group try/except in the processing pipeline | Paper still reaches `READY` if at least metadata extraction succeeded; otherwise `FAILED` | Dashboard shows which fields are missing/failed | `PAPER_PROCESSED` (INFO, with `partial=true` if applicable) |

## Retry policy (summary)

- AI calls: up to 2 retries, exponential backoff, capped total wait ~20s
  per extraction group before giving up on that group specifically.
- Failures are always scoped to the smallest unit possible (one extraction
  group, one field) — a single bad LLM call must never fail the entire
  paper if other groups succeeded.

## Recovery

Users can retry a failed paper via `/reanalyze` (P1) or by re-uploading;
partial failures are visible per-field on the Paper Detail page so a
reviewer knows exactly what's missing.
