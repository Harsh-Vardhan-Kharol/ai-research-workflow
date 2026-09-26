# Project Overview

## What this is

ResearchFlow AI turns unstructured PDF research papers into structured, evidence-backed,
confidence-scored research knowledge, with human review for uncertain extractions and
cross-paper comparison/analytics.

Pipeline (corrected):

```
PDF upload
  -> file validation (type, size, hash-based duplicate check)
  -> PyMuPDF text extraction (page-preserving)
  -> section detection (heuristic, tolerant of variation)
  -> targeted AI extraction (per extraction group, section-scoped where possible)
  -> schema validation (Pydantic)
  -> evidence extraction + similarity validation
  -> confidence calculation (deterministic signals)
  -> conditional human review (low-confidence items only)
  -> SQLite persistence
  -> live analytics + cross-paper comparison
  -> dashboard
```

Processing runs as a FastAPI background task per paper (no queue/worker infrastructure).

## What this explicitly is NOT

- Not a PDF chatbot / generic RAG app / generic LLM wrapper.
- Not an autonomous research agent — there is no agentic planning or tool-selection loop.
- Not a multi-user SaaS product. Single local user, no auth system.
- Not dependent on a vector database. Structured relational data is the knowledge layer.

## Target users

Primary: B.Tech/M.Tech students, thesis/project students, individual researchers.
Secondary (future, not MVP): professors, small research labs.

## Guiding principle

AI is used only where semantic interpretation of scientific language is required
(extraction of research problem, methodology, findings). Everything countable,
validatable, or rule-based (file checks, schema validation, confidence math,
frequency analytics, comparison, workflow state) is deterministic code — never an
LLM call. See `AI_ARCHITECTURE.md` for the exact boundary.

## Minimum Demo-Safe Version (protect this above everything else)

1. Upload a PDF, get page-preserved text + detected sections.
2. Run targeted AI extraction for: metadata, research problem, methodology,
   datasets/metrics, key results.
3. Validate output against Pydantic schemas.
4. Map evidence for each extracted item, with similarity-based validation.
5. Compute a confidence score per extracted item.
6. Persist everything in SQLite.
7. Dashboard: view one processed paper's structured data with confidence badges.
8. Click an extracted item -> see its evidence (page, section, source passage).
9. Compare 2–3 papers side by side on shared fields.
10. Demonstrate one low-confidence item going through Accept/Edit/Reject review.

Limitations/future-work extraction, full research-pattern analytics across many
papers, and review-history UI polish are valuable but are fast-follow, not
demo-blocking. See `REQUIREMENTS.md` for the full priority ordering.
