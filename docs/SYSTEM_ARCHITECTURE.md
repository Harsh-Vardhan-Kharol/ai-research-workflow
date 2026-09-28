# System Architecture

## Component overview

```
┌────────────┐     ┌─────────────┐     ┌──────────────────┐
│ Streamlit  │<--->│  FastAPI    │<--->│  SQLite (single   │
│ Frontend   │ HTTP│  Backend    │ SQL │  file, WAL mode)   │
└────────────┘     └──────┬──────┘     └──────────────────┘
                          │
              ┌───────────┴────────────┐
              │                        │
      ┌───────▼───────┐       ┌────────▼─────────┐
      │ PDF Processing │       │ AIExtractionSvc   │
      │ (PyMuPDF, sync)│       │ (adapter pattern)  │
      └───────┬────────┘       └────────┬──────────┘
              │                         │
      ┌───────▼─────────────────────────▼─────────┐
      │ Evidence Mapper -> Confidence Calculator    │
      │ (deterministic, no LLM calls)               │
      └──────────────────────────────────────────────┘
```

## Processing model (corrected — no queue infrastructure)

The Streamlit client runs separately and uses HTTP only. Its base URL is
configured with `RESEARCHFLOW_API_URL` (default `http://localhost:8000`). It
does not import backend repositories/models or open SQLite. Start it with
`streamlit run frontend/app.py` after starting FastAPI.

Paper processing runs as a single FastAPI `BackgroundTasks` job triggered by
`POST /api/v1/papers/{id}/process`. The paper's `status` column is the source
of truth for progress; the frontend polls `GET /api/v1/papers/{id}/status`.
This is intentionally single-process and sequential — acceptable because the
MVP is a single-operator local tool processing a handful of papers at a time.
Do not introduce Celery/RQ/Redis; if throughput ever becomes a real problem,
that is a documented future-scope decision, not an MVP one.

Status state machine (per paper):

```
UPLOADED -> EXTRACTING_TEXT -> TEXT_EXTRACTED -> DETECTING_SECTIONS -> EXTRACTING_AI
   -> VALIDATING -> MAPPING_EVIDENCE -> SCORING_CONFIDENCE -> READY
                                                    \-> FAILED (terminal, with reason)
```
`READY` papers may have individual extractions flagged `PENDING_REVIEW`; this
does not change the paper's own `status`.

## Component responsibilities

- **PDF Processing** (`app/services/pdf_processor.py`): file validation, hash
  computation, and page-preserving text extraction. **Section Detector**
  (`app/services/section_detector.py`) independently matches standalone
  headings against the persisted page text and returns page-aware sections.
  Both are deterministic and make no AI calls.
- **AIExtractionService** (`app/services/ai_extraction.py`): thin orchestration
  layer that calls the configured provider adapter per extraction group,
  returns raw JSON-like dicts. Never touches the database directly.
- **Provider Adapter** (`app/services/ai_providers.py`): provider protocol,
  configurable OpenAI-compatible hosted adapter, and deterministic mock.
  Enforces structured JSON-schema output and bounded retry-with-repair.
- **Schema Validator** (`app/schemas/extraction.py`): Pydantic models; the
  only gate between AI output and persistence.
- **Evidence Mapper** (`app/services/evidence_mapper.py`): deterministic
  similarity matching between claimed evidence text and actual page text.
- **Confidence Calculator** (`app/services/confidence.py`): deterministic,
  pure function of validated data + evidence match results. See
  `CONFIDENCE_SYSTEM.md`.
- **Repository layer** (`app/database/repository.py`): all SQL access;
  nothing else touches the DB directly.
- **Analytics** (`app/services/analytics.py`): pure SQL/pandas aggregation
  over `extractions`, computed live (no cache table).
- **Frontend** (`frontend/`): Streamlit pages calling the FastAPI backend
  over HTTP only — no direct DB or AI access from the frontend process.

Phase 4 persists validated group payloads in `ai_extraction_groups` as an
intermediate checkpoint. Phase 5 materializes non-null claims into
`extractions`, independently maps each source proposal against stored page
text, and persists the match in `evidence`. The Phase 5 terminal status is
`SCORING_CONFIDENCE`; Phase 6 then scores each extraction from its persisted
evidence and advances successful papers to `READY`. Review-required claims
remain `PENDING_REVIEW` without blocking paper readiness. The proposal and
matched passage remain separate fields.

Phase 7 handles review through `POST /api/v1/extractions/{id}/review` and the
repository's atomic SQLite transaction. Only `PENDING_REVIEW` items can be
reviewed. The API persists ACCEPTED/EDITED/REJECTED records and item statuses;
the original `field_value`, evidence, and confidence stay unchanged. An EDIT
value is available from the review record and does not inherit the AI claim's
evidence or confidence. Review does not change paper-level `READY` status.

Phase 9 adds `POST /api/v1/analytics/compare`. Its API route calls a
comparison service, which uses the repository to fetch selected paper states
and usable extraction rows in bounded queries. The service aggregates only
persisted structured `field_value` records; it does not load page text or call
an LLM. Each result retains paper IDs and extraction IDs, alongside
confidence/review metadata. READY is the only eligible paper state. Rejected
items are excluded; pending, accepted, and edited items remain visible with
their status. For edited items the original value remains the comparison
value, and the separate human-reviewed value is exposed without inheriting
the original confidence/evidence. Streamlit consumes this API over HTTP.

Comparison dimensions follow the current validated extraction schema:
research problem/objective, methodology/models, datasets, experimental setup,
evaluation metrics, and key results. Limitations are explicitly unavailable
until the persisted extraction schema supports them. Normalization is limited
to Unicode NFKC, casefolding, punctuation-to-space, and whitespace collapse;
it does not infer semantic equivalence.

## Data flow contract

Nothing downstream of "Schema Validator" ever sees raw, unvalidated AI output.
Nothing downstream of "Evidence Mapper" computes confidence without evidence
match results already attached. This ordering is authoritative and must not
be silently reordered.

## Deviation Log

- 2026-09-27: Added `TEXT_EXTRACTED` between text extraction and section
  detection as an observable checkpoint for incremental implementation.
- 2026-09-27: Added a deterministic section-detector service. The processing
  service reads persisted page text and stores its output in `paper_sections`;
  the workflow remains at `DETECTING_SECTIONS` until AI processing exists.
- 2026-09-27: Phase 4 adds a provider boundary, strict group schemas, and
  validated AI group checkpoints. Hosted configuration requires a caller-
  supplied OpenAI-compatible endpoint, model, and API key. Mock mode supports
  deterministic tests. Extraction stops at `VALIDATING` pending later
  evidence and confidence phases.
- 2026-09-28: Phase 5 adds deterministic page-text evidence mapping and
  explicit `MATCHED`/`WEAK`/`UNAVAILABLE`/`FAILED` states. Source proposals
  remain stored separately from matched spans. Processing ends at
  `SCORING_CONFIDENCE`; no confidence values are calculated.
- 2026-09-28: Phase 6 adds deterministic weighted scoring, stored signal
  breakdown and review reasons, separate evidence-driven routing, and the
  `SCORING_CONFIDENCE -> READY` transition. No additional model call is used.
- 2026-09-28: Phase 7 adds one atomic backend decision per pending extraction;
  no dashboard or paper-level status transition is part of this phase.
- 2026-09-28: Phase 9 adds deterministic comparison and pattern detection over
  validated extraction rows without adding a table or changing confidence,
  evidence, or review workflow semantics.
