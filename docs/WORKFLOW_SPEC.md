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
**Deterministic:** standalone, exact heading-pattern matching (case-
insensitive, tolerant of numbering, punctuation, whitespace, and short wrapped
headings) against known heading families: Abstract, Introduction, Related
Work, Literature Review, Background, Methodology/Methods, Materials and
Methods, Proposed Method, Experiments, Results, Discussion, Conclusion,
Limitations, Future Work, References/Bibliography. Body prose is not accepted
as a heading merely because it mentions one of these terms. Each detected
heading becomes a `paper_sections` row spanning until the next detected
heading, with its name, page range, and body content.
**Fallback:** if no headings are detected, no section rows are created for
this paper and processing records `SECTION_DETECTION_COMPLETED` with
`sections_found=0`. Later extraction groups use whole-document (capped) text
with `section_detected = false`. Detection or section-persistence errors are
logged and leave the successfully persisted page text intact at
`TEXT_EXTRACTED`; section detection alone never fails PDF extraction.

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
Per `CONFIDENCE_SYSTEM.md`. Runs per valid extraction item using its persisted
evidence row, then stores the score, level, four signals, review-required flag,
and stable review reasons atomically. A missing evidence row is treated as
unavailable; a malformed evidence record fails confidence processing safely.
Unavailable, weak, failed, or low-confidence items enter `PENDING_REVIEW`.
Other items enter `ACCEPTED`. Confidence completion advances the paper from
`SCORING_CONFIDENCE` to `READY`; individual pending-review items do not block
paper readiness.

### 8. Persistence
All `extractions` and `evidence` rows written in a single transaction per
extraction group (so a partial group failure doesn't leave orphaned rows).

### 9. Review (conditional)
Any extraction with `review_required = true` appears on the Review page.
Only an extraction in `PENDING_REVIEW` may be reviewed. ACCEPT writes an
`ACCEPTED` review record and changes item status to `ACCEPTED`; EDIT writes an
`EDITED` record with a validated `reviewed_value` and changes item status to
`EDITED`; REJECT writes a `REJECTED` record and changes item status to
`REJECTED`. Every record preserves `original_value`, optional
`reviewed_value`, optional comment, and `reviewed_at`. The extraction's
`field_value`, proposed provenance, matched evidence, and confidence remain
unchanged. The reviewed value is explicit in the record and does not inherit
the original confidence/evidence claim. The paper remains `READY`; reviewing
one item does not change paper status or imply that other pending items have
been reviewed. A final decision cannot be resubmitted through the API.

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
`PENDING_REVIEW` — this is normal and does not block `READY`.

## Extraction-item status values

`PENDING_REVIEW` (low score or weak/unavailable/failed evidence) -> `ACCEPTED`
| `EDITED` | `REJECTED`. Other items start at `ACCEPTED`; MEDIUM confidence is
review suggested but does not block acceptance.

## Deviation Log

- 2026-09-27: Added the explicit `TEXT_EXTRACTED` intermediate state so the
  incremental PDF phase can report completed page extraction without claiming
  section detection or later stages have run. Defined “near-zero” as fewer
  than 20 non-whitespace characters to make scanned/blank PDF handling
  deterministic and testable.
- 2026-09-27: Section detection persists sections and then leaves the paper at
  `DETECTING_SECTIONS`, the last reached stage until AI extraction is built.
  Successful page persistence is still separately committed at
  `TEXT_EXTRACTED` before this stage starts.
- 2026-09-27: Phase 4 runs the five P0 extraction groups independently and
  stores only Pydantic-validated group payloads in `ai_extraction_groups`.
  `VALIDATING` is its intermediate checkpoint; partial AI group failures are
  retained while successful groups remain available for the evidence phase.
- 2026-09-28: Phase 5 materializes non-null validated claims into `extractions`,
  stores each original AI source proposal separately, then maps it against
  persisted pages. It ends at `SCORING_CONFIDENCE`; confidence scoring and
  `READY` remain unimplemented. Every non-null claim gets a one-to-one evidence
  record, using explicit `UNAVAILABLE`/`FAILED` states instead of losing the
  mapping outcome. Per-group evidence writes are transactional.
- 2026-09-28: Phase 6 computes and persists deterministic confidence per item,
  routes weak/unavailable/failed evidence independently of score, and advances
  successful scoring from `SCORING_CONFIDENCE` to `READY`.
- 2026-09-28: Phase 7 implements the item-level review actions as specified;
  review status is terminal per item while paper-level `READY` remains
  independent. The original AI value and confidence/evidence provenance are
  retained.
