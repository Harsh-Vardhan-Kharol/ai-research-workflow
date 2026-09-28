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
| LLM timeout | Adapter call exceeds `AI_TIMEOUT_SECONDS` | Bounded retry up to `MAX_AI_RETRIES`, then fail just that extraction group | "Some fields could not be extracted; you can retry processing." | `AI_EXTRACTION_FAILED` (ERROR, per group) |
| LLM rate limit | Provider 429 | Exponential backoff, max 2 retries, then fail that group | same as above | `AI_EXTRACTION_FAILED` (ERROR) |
| Invalid JSON from LLM | JSON parse fails | Bounded repair attempts with a schema reminder, then fail that group | same as above | `AI_EXTRACTION_FAILED` (ERROR) |
| Schema validation failure | Pydantic rejects the structured response | Fail that group; store no provider payload as successful | Visible in group state; retry processing | `VALIDATION_FAILED` (WARNING, per group) |
| Missing required fields / empty response / unexpected shape | Provider response parsing or Pydantic validation | Fail the affected group and retain a safe failure code | Visible in group state; retry processing | `AI_EXTRACTION_FAILED` or `VALIDATION_FAILED` |
| Hosted provider configuration error | Missing `AI_API_KEY`, `AI_MODEL_NAME`, or `AI_BASE_URL` | Fail each affected group without logging credentials | Visible in group state | `AI_EXTRACTION_FAILED` (ERROR) |
| Missing evidence source | AI source passage is null/blank | Retain the extraction and write an `UNAVAILABLE` evidence row with score 0 and null actual location | Evidence panel shows "no evidence available" | `EVIDENCE_MAPPED` (INFO, `matched=false`) |
| Invalid/missing page | Proposed page is invalid or absent from `paper_pages` | Search all stored pages; set `page_corrected=true` for fallback; if no candidate exists, persist `UNAVAILABLE` | Evidence panel identifies unavailable match | `EVIDENCE_MAPPED` (INFO) |
| No matching passage | Source has no candidate in the eligible page(s) | Persist score 0 as `UNAVAILABLE`; retain the AI claim and proposal | Evidence panel shows "no evidence available" | `EVIDENCE_MAPPED` (INFO, `matched=false`) |
| Weak/partial passage | Best candidate score is below `MIN_EVIDENCE_THRESHOLD` | Persist actual matched span and score as `WEAK` | Evidence panel shows "evidence not strongly matched" | `EVIDENCE_MAPPED` (INFO) |
| Malformed source / mapper failure | Source claim cannot be evaluated | Keep extraction, persist `FAILED` evidence state and safe failure code; continue other claims | Visible in evidence details | `EVIDENCE_MAPPING_FAILED` (WARNING) |
| Evidence database error | Exception on per-group evidence write | Roll back that group transaction, preserve pages/sections/validated AI groups and earlier groups; mark paper `FAILED` for retry | "A database error occurred while saving evidence." | `EVIDENCE_PERSISTENCE_FAILED` (ERROR) |
| Partial evidence failure | One or more claims map to `FAILED`, other groups/items map normally | Persist each item outcome; score available claims, route failed evidence to review, and reach `READY` with `partial_evidence_mapping` retained | Failed items and safe reason are visible for review | `EVIDENCE_MAPPING_FAILED` (WARNING) |
| Missing evidence at confidence scoring | Extraction has no evidence row or has `UNAVAILABLE` evidence | Score evidence and relevance as 0, require review with `evidence_unavailable`, continue scoring | Expose score and review reason | `CONFIDENCE_SCORING_COMPLETED` (INFO) |
| Weak/failed evidence at confidence scoring | Persisted state is `WEAK` or `FAILED` | Score evidence as 0, require review with `evidence_weak` or `evidence_mapping_failed`; failed mapping is not treated as a false claim | Expose score and review reason | `CONFIDENCE_SCORING_COMPLETED` (INFO) |
| Invalid confidence/evidence data | Unknown state, malformed matched passage, non-finite/out-of-range number, or inconsistent evidence row | Reject the confidence run; mark the paper `FAILED` with safe `confidence_calculation_failed`; never clamp or report a high score | "Confidence could not be calculated for this paper." | `CONFIDENCE_CALCULATION_FAILED` (ERROR) |
| Confidence database write failure | Atomic per-paper scoring transaction raises | Roll back all confidence writes and do not mark `READY`; mark paper failed with safe persistence reason if possible | "A database error occurred while saving confidence results." | `CONFIDENCE_PERSISTENCE_FAILED` (ERROR) |
| Database errors | Exception on write | Roll back the transaction for that group only; do not corrupt already-committed groups | "A database error occurred while saving results." | `PROCESSING_FAILED` (ERROR) |
| Duplicate paper (same hash) | Hash check on upload | 409, do not re-process | "This file has already been uploaded (paper #{id})." | `UPLOAD_REJECTED` (INFO) |
| Partial extraction/mapping | Some groups fail while other groups or items persist | Score available extraction items; preserve the partial failure reason and reach `READY` if confidence persistence succeeds | Dashboard shows which fields are missing/failed | `PAPER_PROCESSED` (INFO, with `partial=true` if applicable) |

## Retry policy (summary)

- AI transient calls: up to `MAX_AI_RETRIES` retries, exponential backoff;
  each request is bounded by `AI_TIMEOUT_SECONDS`.
- Evidence matching uses only stored `paper_pages`; it does not call a model
  or external service.
- Confidence math uses only validated extraction rows and persisted evidence;
  malformed data fails closed, while missing evidence scores zero and routes
  to review independently of score.
- Failures are always scoped to the smallest unit possible (one extraction
  group, one field) — a single bad LLM call must never fail the entire
  paper if other groups succeeded.

## Recovery

Users can retry a failed paper via `/reanalyze` (P1) or by re-uploading;
partial failures are visible per-field on the Paper Detail page so a
reviewer knows exactly what's missing.
