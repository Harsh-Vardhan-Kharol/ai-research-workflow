# Development Roadmap (7–14 day plan)

This assumes a solo developer. Days are units of effort, not strict
calendar days — compress or stretch as needed, but preserve the order and
never skip ahead to P1 items before the Demo-Safe Core (P0) is fully
working end-to-end.

## Days 1–2: Foundation
- Project scaffolding per `SYSTEM_ARCHITECTURE.md` structure.
- SQLite schema from `DATABASE_SCHEMA.md`, repository layer, basic tests.
- Upload + validation endpoint, file storage, duplicate-hash check.

## Days 3–4: Deterministic pipeline (no AI yet)
- PyMuPDF page-preserving extraction.
- Section detection with fallback.
- Status state machine wired to `BackgroundTasks`.
- Unit tests for both, using sample papers in `data/sample_papers/`.

## Days 5–7: AI extraction + validation
- Provider adapter (hosted API default) + `AIExtractionService`.
- Pydantic schemas for the 5 P0 extraction groups.
- Prompt injection delimiting per `SECURITY.md`.
- Retry/repair logic for malformed JSON.
- Integration tests with mocked provider.

## Days 8–9: Evidence + confidence
- Evidence Mapper with `rapidfuzz` similarity.
- Confidence Calculator per the revised formula.
- Resolve and document the zero-evidence/LOW-forcing decision flagged in
  `CONFIDENCE_SYSTEM.md`.
- Persistence of `extractions` + `evidence` rows.

## Day 10: Review workflow
- Review endpoint + `review_records`.
- Wire status transitions.

## Days 11–12: Frontend
- Streamlit pages: Upload, Papers, Paper Detail (with confidence badges +
  evidence viewer), Review.
- **Checkpoint: the Minimum Demo-Safe Version from `REQUIREMENTS.md` must
  be fully working end-to-end at this point.** Do not proceed to P1 work
  until this checkpoint passes using `DEMO_GUIDE.md` as the script.

## Days 13–14 (if time remains): P1 fast-follows
- Comparison view, live analytics endpoints + charts page.
- Limitations/future-work extraction groups.
- Reanalyze endpoint, review-history display.

If time runs out before day 13, stop at the P0 checkpoint — that version is
demo-safe on its own and must never be left broken in favor of partially
built P1 features.

## Documentation consistency note

`REQUIREMENTS.md` classifies the 2–3 paper comparison view as P0, while this
roadmap places comparison under the Days 13–14 fast-follows. This is an
unresolved planning inconsistency, not a scope change: comparison remains in
the MVP. Implementation follows functional dependencies (ingestion, text and
section extraction, evidence, confidence, then comparison) so comparison is
built once the structured records it consumes exist.

## Deviation Log

- 2026-09-27: Recorded the existing P0/P1 scheduling inconsistency. No scope
  change was made: comparison remains in the MVP and is sequenced after the
  extraction, evidence, and confidence data it depends on.
