# Workflow Specification

## Full pipeline, step by step

### 1. Upload
**Input:** PDF file via `POST /api/v1/papers/upload`.
**Deterministic checks:** file extension + MIME sniff is PDF; size ≤
`MAX_UPLOAD_SIZE_MB`; SHA-256 hash computed and checked against existing
`papers.file_hash` for duplicates.
**Output:** `papers` row created, `status = UPLOADED`.
**Failure modes:** wrong type -> 400 with message; oversized -> 413;
duplicate hash -> 409 with reference to the existing paper id.

### 2. Text extraction
**Trigger:** `POST /api/v1/papers/{id}/process`.
**Deterministic:** PyMuPDF opens the file; extracts text per page into
`paper_pages` rows (`page_number`, `text`).
**Failure modes:** corrupted PDF (PyMuPDF raises) -> `status = FAILED`,
`failure_reason = "corrupted_pdf"`; near-zero extracted text across all
pages (likely a scanned/image-only PDF) -> `status = FAILED`,
`failure_reason = "no_extractable_text"` (OCR is explicitly out of scope —
do not attempt to add it). A zero-page PDF fails as `empty_pdf`. For this
implementation, near-zero text means fewer than 20 non-whitespace characters
across all pages. Successful page persistence ends at `TEXT_EXTRACTED`; the
next stage is `DETECTING_SECTIONS`.

### 3. Section detection
**Deterministic:** heading-pattern matching (case-insensitive, tolerant of
numbering like "3. Methodology" or "III. METHOD") against a known-heading
list (Abstract, Introduction, Related Work, Method(ology|s)?, Proposed
Method, Experiments, Results, Discussion, Limitations, Conclusion,
Future Work, References). Each detected heading becomes a `paper_sections`
row spanning until the next detected heading.
**Fallback:** if no headings are detected, no section rows are created for
this paper, and every extraction group falls back to whole-document
(capped) text with `section_detected = false` — never fail the pipeline
solely because heading detection found nothing.

### 4. AI extraction
**Per extraction group** (see `AI_ARCHITECTURE.md` targeting table): call
`AIExtractionService`, get raw structured output.
**Failure modes:** provider timeout -> retry up to `MAX_AI_RETRIES`, then
mark that specific group's extractions `FAILED` (does not fail the whole
paper — other groups can still succeed); provider returns malformed JSON ->
one repair retry with the parse error included, then same failure handling
as timeout; rate limit -> exponential backoff (max 2 retries) then fail
that group.

### 5. Schema validation
**Deterministic:** Pydantic models per extraction group. Invalid fields are
dropped (not the whole extraction) with the reason logged
(`VALIDATION_FAILED` event); valid fields proceed.

### 6. Evidence mapping
Per `EVIDENCE_SYSTEM.md`. Runs per valid extraction item.

### 7. Confidence calculation
Per `CONFIDENCE_SYSTEM.md`. Runs per valid extraction item, using its
evidence result.

### 8. Persistence
All `extractions` and `evidence` rows written in a single transaction per
extraction group (so a partial group failure doesn't leave orphaned rows).

### 9. Review (conditional)
Any extraction with `review_required = true` appears on the Review page.
Reviewer actions (Accept/Edit/Reject) write a `review_records` row and
update the extraction's `status`.

### 10. Analytics / comparison
Computed live from `extractions` at request time (no cache table). See
`API_SPECIFICATION.md` for the analytics/comparison endpoints.

## Status state machine (paper-level)

```
UPLOADED -> EXTRACTING_TEXT -> TEXT_EXTRACTED -> DETECTING_SECTIONS -> EXTRACTING_AI
   -> VALIDATING -> MAPPING_EVIDENCE -> SCORING_CONFIDENCE -> READY
                                                    \-> FAILED
```
A paper reaching `READY` may still have individual `extractions` in
`REVIEW_REQUIRED` — this is normal and does not block `READY`.

## Extraction-item status values

`PENDING_REVIEW` (only if low confidence) -> `ACCEPTED` | `EDITED` | `REJECTED`.
High/medium confidence items start directly at `ACCEPTED` (auto-accepted per
`CONFIDENCE_SYSTEM.md` thresholds) but remain editable later.

## Deviation Log

- 2026-09-27: Added the explicit `TEXT_EXTRACTED` intermediate state so the
  incremental PDF phase can report completed page extraction without claiming
  section detection or later stages have run. Defined “near-zero” as fewer
  than 20 non-whitespace characters to make scanned/blank PDF handling
  deterministic and testable.
