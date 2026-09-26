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

### extractions
One row per extracted **item** (scalar field = 1 row; list field = N rows,
one per list element).
| Column | Type | Constraints |
|---|---|---|
| id | INTEGER | PK |
| paper_id | INTEGER | FK -> papers.id ON DELETE CASCADE, indexed |
| field_name | TEXT | not null, e.g. "research_problem", "dataset", "key_result" |
| item_index | INTEGER | not null, 0 for scalar fields, 0..N-1 for list items |
| field_value | TEXT | not null |
| confidence_score | REAL | not null |
| confidence_level | TEXT | not null, HIGH/MEDIUM/LOW |
| status | TEXT | not null, PENDING_REVIEW/ACCEPTED/EDITED/REJECTED |
| section_detected | INTEGER | not null, boolean 0/1 (was the expected section found) |
| created_at | TEXT | not null |
| updated_at | TEXT | not null |

Unique constraint: (paper_id, field_name, item_index).
Index: (paper_id), (status) for review-page queries.

### evidence
| Column | Type | Constraints |
|---|---|---|
| id | INTEGER | PK |
| extraction_id | INTEGER | FK -> extractions.id ON DELETE CASCADE, UNIQUE (one evidence row per extraction in MVP), indexed |
| page_number | INTEGER | nullable |
| section_name | TEXT | nullable |
| source_text | TEXT | not null |
| evidence_score | REAL | not null |
| page_corrected | INTEGER | not null, boolean 0/1 |
| created_at | TEXT | not null |

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

## Deletion behavior

Deleting a paper (`DELETE /api/v1/papers/{id}`) cascades to `paper_pages`,
`paper_sections`, `extractions`, `evidence`, and `review_records`. This is a
hard delete for MVP — no soft-delete/undo requirement in scope.

## Migration strategy

No migration framework required for MVP (single developer, schema unlikely
to change post-freeze). If the schema must change during development,
regenerate the SQLite file from the updated `CREATE TABLE` statements —
do not hand-write ALTER migrations unless real demo data must be preserved
across a schema change late in the project.
