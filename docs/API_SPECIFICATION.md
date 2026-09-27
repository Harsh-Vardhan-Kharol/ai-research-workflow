# API Specification

Base path: `/api/v1`. No authentication for MVP (single local operator).
All responses JSON. Errors use `{"error": {"code": str, "message": str}}`.

## Papers

### POST /papers/upload
Multipart file upload (PDF only).
- 201 -> `{ "id": int, "status": "UPLOADED", "file_name": str }`
- 400 -> invalid file type
- 413 -> file exceeds `MAX_UPLOAD_SIZE_MB`
- 409 -> duplicate file_hash, includes `existing_paper_id`

### GET /papers
List papers (id, title, status, created_at). Supports `?status=` filter.

### GET /papers/{paper_id}
Full paper record including counts of extractions by confidence level.
- 404 if not found.

### DELETE /papers/{paper_id}
Hard delete, cascades per `DATABASE_SCHEMA.md`. 204 on success.

### POST /papers/{paper_id}/process
Triggers background processing (idempotent: if already `READY` or
in-progress, returns 409 with current status rather than double-processing).
- 202 -> `{ "status": "EXTRACTING_TEXT" }`
- Successful page text is committed at `TEXT_EXTRACTED` before section
  detection begins. Completed section detection leaves status at
  `DETECTING_SECTIONS` until the later AI stage is implemented. Reprocessing
  either state returns 409 with its current status.

### GET /papers/{paper_id}/status
- 200 -> `{ "status": str, "failure_reason": str|null }`

### POST /papers/{paper_id}/reanalyze (P1)
Re-runs AI extraction only (not text/section extraction) on an already
text-extracted paper. Same idempotency rule as `/process`.

## Extractions

### GET /papers/{paper_id}/extractions
All extraction items for a paper, grouped by `field_name`, each with its
confidence object (see `CONFIDENCE_SYSTEM.md` output shape) and evidence
summary.

### GET /extractions/{extraction_id}
Single extraction item, full detail.

### GET /extractions/{extraction_id}/evidence
Evidence record for that extraction (page, section, source_text,
evidence_score).

### POST /extractions/{extraction_id}/review
Body: `{ "action": "ACCEPT"|"EDIT"|"REJECT", "reviewed_value": str|null,
"comment": str|null }`. `reviewed_value` required only for `EDIT`.
Writes a `review_records` row and updates the extraction's status.
- 200 -> updated extraction
- 400 -> `EDIT` without `reviewed_value`

## Analytics (computed live, no cache)

### GET /analytics/overview
Paper count, extraction count by confidence level, review-pending count.

### GET /analytics/methods
### GET /analytics/datasets
### GET /analytics/metrics
Frequency counts of `field_value` across `extractions` for the relevant
`field_name`, across all `READY` papers.

### GET /analytics/limitations (P1)

## Comparison

### POST /compare
Body: `{ "paper_ids": [int, int, int] }` (2–3 ids).
Returns a field-by-field table: for each shared `field_name`, each paper's
value(s) and confidence.
- 400 if fewer than 2 or more than 3 ids given.

## Deviation Log

- 2026-09-27: Documented the section-detection checkpoint; page text remains
  separately committed at `TEXT_EXTRACTED` before detection starts.

## Idempotency & retries

`/process` and `/reanalyze` are idempotent by paper status check (see
above), not by an idempotency-key header — sufficient for a single-operator
tool. No rate limiting is implemented for MVP (single local user); if this
changes, document it here first.
