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

### POST /papers/upload-batch
Multipart upload of one or more PDF files using repeated `files` fields.
Each file is validated and stored independently so a rejected file does not
prevent other files in the same request from being uploaded.
- 201 -> `{ "uploaded": [...], "rejected": [...] }`
- `uploaded` items use the same shape as `/papers/upload`.
- `rejected` items contain `file_name`, `code`, `message`, and optional
  `existing_paper_id`.

### GET /papers
Returns `{ "papers": [...] }` with id, title, file_name, status, created_at,
updated_at, and `pending_review_count`. Papers are ordered newest first.

### GET /papers/{paper_id}
Full paper record including metadata, failure reason, pending review count, and
counts of extractions by confidence level (`UNSCORED` when absent).
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

## Multi-paper comparison

### POST /analytics/compare
Body: `{ "paper_ids": [int, ...] }`; at least two unique IDs. The request
accepts two or more papers. Every paper must exist and be `READY`; a missing
paper returns 404 and any other paper state returns 409. Duplicate IDs or an
invalid/minimum-size payload return 422 using the standard error envelope.

The response contains `selected_papers`, `dimensions`,
`pairwise_differences`, `missing_information`, and `patterns`. Dimensions
include research problem/objective, methodology/models, datasets, experimental
setup, evaluation metrics, key results, limitations, and future work. Top-level
`limitations` and `future_work` summaries contain availability, frequencies,
and repeated-value patterns. Their source objects also pair each extraction
ID with its contributing paper ID. `gap_candidates` contains the candidate type,
title, explanation, scope, basis, relevant values, supporting paper/extraction
IDs, and source records with confidence/review metadata.
Every per-paper value and frequency source contains the extraction ID,
original `field_value`, confidence score/level, review-required flag, item
status, review status, and separate `reviewed_value` when one exists.
Frequency `count` counts distinct papers, while `sources` retains each
contributing extraction record. Pairwise results report exact normalized
shared/first-only/second-only values and whether each paper reported that
dimension (`available` is false for unsupported dimensions). Missing
information means “not extracted/reported in the
structured record,” not proof that the paper omits the subject.

Only `READY` papers qualify. Extraction items in `PENDING_REVIEW`, `ACCEPTED`,
and `EDITED` are included with their confidence and review metadata;
`REJECTED` and pre-scoring `EXTRACTED` rows are excluded. For edited items,
the analytical value remains the immutable original `field_value`; the human
`reviewed_value` is returned separately and does not inherit confidence or
evidence. No raw PDF text or LLM is used.

Normalization applies Unicode NFKC, casefolding, punctuation-to-space, and
whitespace collapse. It does not use synonyms, stemming, abbreviations, or
semantic equivalence. Original values remain in the response beside the
normalized key.

Pattern rules are deterministic: a value appearing in at least two papers
creates a `repeated_value` pattern; a supported dimension reported by fewer
than half of selected papers creates a `sparse_field` pattern; two or more
papers with reported, distinct methodology/model values create
`methodological_variation`. Limitations and future work use the same
normalization and repeated-value rule.

Candidate types are `DATASET_CONCENTRATION`, `METHOD_CONCENTRATION`,
`SPARSE_DIMENSION`, `RECURRING_LIMITATION`, `RECURRING_FUTURE_WORK`, and
`METHOD_DATASET_ABSENCE`. Concentration defaults to at least 70% of selected
papers and at least two distinct papers; configure it with
`GAP_CONCENTRATION_THRESHOLD`. Sparse dimensions default to less than 50%
coverage and require at least one supporting claim; configure with
`GAP_SPARSE_THRESHOLD`. Recurrence requires two papers. Method/dataset absence
means both values occur individually but never co-occur in a selected paper's
structured records; it does not prove a field-wide or actual experimental
pairing absence. Every result is a potential gap candidate scoped to the
selected literature. Missing structured records do not prove that no research
exists. The analytics is deterministic and uses no LLM.

### POST /analytics/insights (Phase 11)

Body: `{ "paper_ids": [int, ...] }`, with the same unique-ID, minimum-size,
and READY-paper requirements as `/analytics/compare`. The endpoint runs the
existing deterministic comparison and builds a compact allowlisted insight
input package from its response. It does not read PDF text or independently
query/persist database rows in the insight service.

Success: `{ "status": "completed", "insights": [...] }`. Each insight has a
controlled `type`, `title`, `observation`, `interpretation`, explicit `scope`,
supporting paper and extraction IDs, and optional pattern/candidate IDs. A
`RESEARCH_DIRECTION` also includes `suggested_research_question`, which the UI
labels **SUGGESTED RESEARCH QUESTION**. Gap candidates remain potential
candidates, not confirmed research gaps. Empty `insights` means generation
completed but the supplied analytics did not support a useful interpretation.

The insight output is Pydantic-validated, limited to 10 items, deduplicated,
and checked for exact known paper/extraction/pattern/candidate references,
paper/extraction correspondence, type/dimension alignment, selected-record
scope language, and unsupported numeric claims. Invalid model output returns
502 `INVALID_INSIGHT_OUTPUT`; unavailable or unconfigured AI returns 503
`INSIGHT_PROVIDER_UNAVAILABLE`; provider timeout returns 504
`INSIGHT_TIMEOUT`. Invalid paper selection and database failures use the same
semantics as comparison. None of these failures affects `/analytics/compare`.
The insight service reuses the configured `ProviderAdapter`; mock mode returns
a valid empty insight collection. AI insights are interpretive and are not
authoritative research conclusions.

## Deviation Log

- 2026-09-27: Documented the section-detection checkpoint; page text remains
  separately committed at `TEXT_EXTRACTED` before detection starts.
- 2026-09-28: Phase 6 extends extraction responses with persisted confidence
  signals and review routing. `POST /process` now reaches `READY` after
  successful scoring; review-required items remain pending at item level.
- 2026-09-28: Phase 7 implements the documented extraction review endpoint.
  Review responses expose an optional review record while retaining
  `field_value` as the original AI value; paper status remains unchanged.
- 2026-09-28: Phase 8 implements the documented paper list and detail reads
  used by Streamlit. The list includes pending-review counts; detail includes
  extraction counts grouped by confidence level.
- 2026-09-28: Phase 9 adds `POST /analytics/compare`, live deterministic
  aggregation over READY-paper extraction rows, explicit item review/confidence
  metadata, source-paper traceability, and the Streamlit comparison page.
- 2026-09-29: Phase 10 retains the compare endpoint, adds limitations and
  future-work dimensions/summaries, and returns selected-literature-scoped,
  traceable deterministic gap candidates without schema tables or LLM calls.

## Idempotency & retries

`/process` and `/reanalyze` are idempotent by paper status check (see
above), not by an idempotency-key header — sufficient for a single-operator
tool. No rate limiting is implemented for MVP (single local user); if this
changes, document it here first.
