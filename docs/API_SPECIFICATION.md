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
  detection begins. Processing then runs section detection and the five P0 AI
  extraction groups, maps evidence, calculates confidence, and advances to
  `READY`. Individual extractions can be `PENDING_REVIEW` while the paper is
READY. Partial extraction/evidence failure reasons are retained for the API
and review routing; other in-progress states still return 409.

### GET /papers/{paper_id}/status
- 200 -> `{ "status": str, "failure_reason": str|null }`

### GET /papers/{paper_id}/extraction-groups (Phase 4)
Returns per-group `SUCCEEDED`/`FAILED` state, validated payload when
successful, section-detection/truncation metadata, and a safe failure code.
Provider output that fails schema validation is never returned as a successful
payload. Extraction source passages and page/section claims are unverified.

### POST /papers/{paper_id}/reanalyze (P1)
Re-runs AI extraction only (not text/section extraction) on an already
text-extracted paper. Same idempotency rule as `/process`.

## Extractions

### GET /papers/{paper_id}/extractions
Returns normalized non-null extraction items with their original AI-proposed
source/page/section, independently matched evidence summary, and after scoring:
`confidence_score`, `confidence_level`, `confidence_signals` (object with
`schema_validity`, `evidence_strength`, `source_relevance`, `completeness`),
`review_required`, `review_reasons`, and item `status`. `PENDING_REVIEW` is
independent of score level; see `CONFIDENCE_SYSTEM.md` for reasons and meaning.

### GET /extractions/{extraction_id}
Single extraction item, full detail including confidence and routing output.
After review, `field_value` remains the original AI value and `review` contains
the review record (`original_value`, `reviewed_value`, `review_status`,
`review_comment`, `reviewed_at`). An EDIT response has item status `EDITED`;
its `review.reviewed_value` is the human-reviewed value. Review does not change
the original evidence or confidence fields.

### GET /extractions/{extraction_id}/evidence
Evidence record for that extraction, including both proposed and matched
source/page/section, `evidence_score`, `page_corrected`, `match_status`, and
failure code. Matched means traceability, not factual correctness.

Confidence is included in the extraction response rather than duplicated in a
dedicated endpoint. Missing/unavailable/weak/failed evidence can set
`review_required=true` even when `confidence_level` is MEDIUM or HIGH.

### POST /extractions/{extraction_id}/review
Body: `{ "action": "ACCEPT"|"EDIT"|"REJECT", "reviewed_value": str|null,
"comment": str|null }`. `reviewed_value` required only for `EDIT`.
Requires item status `PENDING_REVIEW`. ACCEPT stores `review_status=ACCEPTED`
and changes item status to `ACCEPTED`; EDIT stores the validated human value
and changes item status to `EDITED`; REJECT stores `review_status=REJECTED`
and changes item status to `REJECTED`. All actions retain the AI value as
`field_value` and as `review_records.original_value`. Comments are optional,
trimmed, and limited to 2,000 characters. Edited values must be non-empty
strings, are trimmed, and are limited to 12,000 characters. This follows the
AI claim schema's string value type without claiming that the original
evidence or confidence validates an edited value. The write is atomic.
- 200 -> updated extraction including its review record
- 400 -> `EDIT` without `reviewed_value` or value supplied for another action
- 404 -> extraction not found
- 409 -> item is not `PENDING_REVIEW` (including duplicate submissions)
- 422 -> malformed action/payload, invalid value type, or size constraint
- 500 -> database write failure; no partial review update is committed

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
- 2026-09-28: Phase 6 extends extraction responses with persisted confidence
  signals and review routing. `POST /process` now reaches `READY` after
  successful scoring; review-required items remain pending at item level.
- 2026-09-28: Phase 7 implements the documented extraction review endpoint.
  Review responses expose an optional review record while retaining
  `field_value` as the original AI value; paper status remains unchanged.

## Idempotency & retries

`/process` and `/reanalyze` are idempotent by paper status check (see
above), not by an idempotency-key header — sufficient for a single-operator
tool. No rate limiting is implemented for MVP (single local user); if this
changes, document it here first.
