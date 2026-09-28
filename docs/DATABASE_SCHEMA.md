# Database Schema (Authoritative)

Engine: SQLite, WAL mode enabled. No ORM required (plain SQL via a thin
repository layer is acceptable and simpler for this scope); SQLAlchemy Core
is fine if preferred, but avoid full ORM relationship-mapping complexity.

## Corrections from the original proposal

1. `extractions` is split so **list-type fields get one row per item**, not
   one row holding a serialized list. This is required for the
   evidence/confidence/review system to apply per-claim, not per-field-group.
2. `analysis_results` table is **dropped** — analytics computed live at MVP
   scale; re-add only if profiling shows it's actually needed.
3. All foreign keys use `ON DELETE CASCADE` so deleting a paper cleans up
   everything derived from it.
4. `papers.file_hash` has a `UNIQUE` constraint (duplicate detection).
5. Indexes added on every foreign key column used in lookups.

## Tables

### papers
| Column | Type | Constraints |
|---|---|---|
| id | INTEGER | PK, autoincrement |
| title | TEXT | nullable (populated after metadata extraction) |
| abstract | TEXT | nullable |
| authors | TEXT | nullable (stored as JSON array string) |
| publication_year | INTEGER | nullable |
| source | TEXT | nullable, e.g. "upload" |
| file_name | TEXT | not null |
| file_hash | TEXT | not null, UNIQUE |
| status | TEXT | not null, enum per `WORKFLOW_SPEC.md` state machine |
| failure_reason | TEXT | nullable |
| created_at | TEXT | not null, ISO timestamp |
| updated_at | TEXT | not null, ISO timestamp |

### paper_pages
| Column | Type | Constraints |
|---|---|---|
| id | INTEGER | PK |
| paper_id | INTEGER | FK -> papers.id ON DELETE CASCADE, indexed |
| page_number | INTEGER | not null |
| text | TEXT | not null |

Unique constraint: (paper_id, page_number).

### paper_sections
| Column | Type | Constraints |
|---|---|---|
| id | INTEGER | PK |
| paper_id | INTEGER | FK -> papers.id ON DELETE CASCADE, indexed |
| section_name | TEXT | not null |
| start_page | INTEGER | not null |
| end_page | INTEGER | not null |
| content | TEXT | not null |

### ai_extraction_groups (Phase 4 checkpoint)
One row per extraction group. This intermediate table stores a Pydantic-
validated group payload as JSON until the evidence/confidence phases write
normalized per-item rows to `extractions` and `evidence`.

| Column | Type | Constraints |
|---|---|---|
| id | INTEGER | PK |
| paper_id | INTEGER | FK -> papers.id ON DELETE CASCADE, indexed |
| group_name | TEXT | not null |
| status | TEXT | not null, SUCCEEDED/FAILED |
| validated_payload | TEXT | nullable; non-null only for SUCCEEDED |
| section_detected | INTEGER | not null, boolean 0/1 |
| truncated | INTEGER | not null, boolean 0/1 |
| failure_code | TEXT | nullable; required only for FAILED |
| created_at | TEXT | not null |
| updated_at | TEXT | not null |

Unique constraint: (paper_id, group_name). Failed groups contain no provider
payload. Successful payloads include model-proposed value, source text, page,
and section claims; those claims are not evidence-verified.

### extractions
One row per extracted **item** (scalar field = 1 row; list field = N rows,
one per list element). Phase 5 materializes non-null claims from the validated
Phase 4 group checkpoint. Proposed source fields preserve the model's claim
separately from the independent result in `evidence`. Until confidence scoring
runs, rows use `status = EXTRACTED` and leave confidence columns null. Scoring
stores the per-item score, level, routing, signal breakdown, and reasons here.
| Column | Type | Constraints |
|---|---|---|
| id | INTEGER | PK |
| paper_id | INTEGER | FK -> papers.id ON DELETE CASCADE, indexed |
| group_name | TEXT | not null, source extraction group |
| field_name | TEXT | not null, e.g. "research_problem", "dataset", "key_result" |
| item_index | INTEGER | not null, 0 for scalar fields, 0..N-1 for list items |
| field_value | TEXT | not null |
| proposed_source_text | TEXT | nullable, original model-proposed passage |
| proposed_page | INTEGER | nullable, original model-proposed page |
| proposed_section | TEXT | nullable, original model-proposed section |
| confidence_score | REAL | nullable until the confidence phase |
| confidence_level | TEXT | nullable until the confidence phase, HIGH/MEDIUM/LOW |
| confidence_signals | TEXT | nullable JSON object with the four deterministic signal values |
| review_required | INTEGER | not null boolean 0/1, default 0 |
| review_reasons | TEXT | nullable JSON array of stable routing reason codes |
| status | TEXT | not null, EXTRACTED/PENDING_REVIEW/ACCEPTED/EDITED/REJECTED |
| section_detected | INTEGER | not null, boolean 0/1 (was the expected section found) |
| created_at | TEXT | not null |
| updated_at | TEXT | not null |

Unique constraint: (paper_id, group_name, field_name, item_index).
Index: (paper_id), (status) for review-page queries.

The JSON fields keep an explainable per-extraction result together without a
redundant confidence table. They are generated by backend code, not accepted
from clients or an LLM. `updated_at` records the scoring write.

### evidence
One independently mapped result per non-null extraction item. `source_text`,
`page_number`, and `section_name` describe the source passage found in stored
paper text; they are not copied from the AI proposal. An empty `source_text`
and null location represent an unavailable match.

| Column | Type | Constraints |
|---|---|---|
| id | INTEGER | PK |
| extraction_id | INTEGER | FK -> extractions.id ON DELETE CASCADE, UNIQUE (one evidence row per extraction in MVP), indexed |
| page_number | INTEGER | nullable |
| section_name | TEXT | nullable |
| source_text | TEXT | not null |
| evidence_score | REAL | not null |
| page_corrected | INTEGER | not null, boolean 0/1 |
| match_status | TEXT | not null, MATCHED/WEAK/UNAVAILABLE/FAILED |
| failure_code | TEXT | nullable, safe mapper failure reason |
| created_at | TEXT | not null |

`MATCHED` means the independently matched passage met
`MIN_EVIDENCE_THRESHOLD`; it confirms traceability only, not factual
correctness. `WEAK` means a passage candidate scored below the threshold.
`UNAVAILABLE` means no source or no candidate was available. `FAILED` means a
malformed source or mapping operation failed. Each result is persisted,
including score 0 and `UNAVAILABLE`/`FAILED` states.

### review_records
| Column | Type | Constraints |
|---|---|---|
| id | INTEGER | PK |
| extraction_id | INTEGER | FK -> extractions.id ON DELETE CASCADE, indexed |
| original_value | TEXT | not null |
| reviewed_value | TEXT | nullable (null if action was Accept/Reject with no edit) |
| review_status | TEXT | not null, ACCEPTED/EDITED/REJECTED |
| review_comment | TEXT | nullable |
| reviewed_at | TEXT | not null |

Each accepted review decision is appended as a record. Review records are not
updated or deleted by the review workflow. The API permits a decision only
while the extraction is `PENDING_REVIEW`, so a completed decision cannot be
submitted again through the normal workflow. `extractions.field_value` remains
the original AI value for every action; for `EDITED`, `reviewed_value` is the
human-reviewed value. Original evidence, confidence, and review reasons also
remain attached to the AI extraction and are not recalculated by review.

## Deletion behavior

Deleting a paper (`DELETE /api/v1/papers/{id}`) cascades to `paper_pages`,
`paper_sections`, `ai_extraction_groups`, `extractions`, `evidence`, and
`review_records`. This is a
hard delete for MVP — no soft-delete/undo requirement in scope.

## Migration strategy

No migration framework required for MVP (single developer, schema unlikely
to change post-freeze). If the schema must change during development,
regenerate the SQLite file from the updated `CREATE TABLE` statements —
do not hand-write ALTER migrations unless real demo data must be preserved
across a schema change late in the project. Phase 6 adds three extraction
columns additively at schema initialization so Phase 5 databases open without
discarding their data.

## Deviation Log

- 2026-09-28: Added `confidence_signals`, `review_required`, and
  `review_reasons` to the existing extraction row. The Phase 6 API requires
  explainable score and routing output; this avoids a redundant confidence
  table.
- 2026-09-28: Phase 7 creates the documented `review_records` table and its
  extraction index during schema initialization. Review decisions retain the
  original extraction value in both `extractions.field_value` and
  `review_records.original_value`; edited values are stored only in
  `review_records.reviewed_value`.
