# Requirements

## Functional requirements (MVP, in priority order)

### P0 — Demo-Safe Core (must not be cut)
1. PDF upload with validation (type, size cap, corrupted-file rejection).
2. Duplicate detection via SHA-256 file hash; reject or flag re-upload of an
   already-processed file.
3. Page-preserving text extraction (PyMuPDF): text is stored per page, never
   flattened into one untraceable string.
4. Section detection tolerant of heading variation (see `WORKFLOW_SPEC.md`).
5. Targeted AI extraction for: metadata (title/authors/year/abstract),
   research problem/objective, methodology/models/algorithms,
   datasets/experimental setup/evaluation metrics, key results.
6. Pydantic schema validation of all AI output before it touches the database.
7. Evidence mapping (page, section, source passage) for every non-null
   extracted item, with similarity-based validation (see `EVIDENCE_SYSTEM.md`).
8. Deterministic confidence scoring per extracted item (see `CONFIDENCE_SYSTEM.md`).
9. Deterministic review routing for low-confidence or weak/unavailable/failed
   evidence items, plus the later Accept / Edit / Reject workflow with original
   value, reviewed value, reviewer comment, and timestamp retained.
10. SQLite persistence per `DATABASE_SCHEMA.md`.
11. Dashboard: paper list, paper detail view with confidence-badged extractions.
12. Evidence viewer: click an extraction, see its supporting passage.
13. Comparison view for 2–3 selected papers on shared fields.
14. Structured logging (see `ERROR_HANDLING.md` for event list) and graceful
    error handling for every failure mode listed there.
15. A reliable, repeatable end-to-end local demo (see `DEMO_GUIDE.md`).

### P1 — Fast-follow (build only after P0 is fully working and demoed)
16. Limitations extraction.
17. Future-work extraction.
18. Cross-paper research-pattern analytics (method/dataset/model/metric/
    limitation frequency, year trends) beyond the 2–3 paper comparison view.
19. Re-analyze endpoint (re-run extraction on an already-uploaded paper).
20. Review-history display (audit trail of prior review actions).

### P2 — Documented future scope, not built
- RAG / vector search over paper corpus.
- Autonomous multi-agent research assistant.
- Automatic paper discovery/download from the web.
- Citation graph analysis.
- Multi-user accounts / enterprise auth.
- Kubernetes / multi-service deployment.

## Non-functional requirements

- Single developer, 7–14 calendar days, working solo.
- Runs entirely on a single local machine for the demo (no required cloud
  infrastructure beyond an optional hosted LLM API call).
- No authentication system; this is a single-operator local tool for the MVP.
- Dependencies kept minimal — every added library must justify its inclusion
  against `TECH_STACK.md`.
- All non-deterministic (AI) output must be validated before persistence;
  no AI output reaches the database directly.
- Paper content is always treated as untrusted input, never as system
  instructions (see `SECURITY.md`).

## Explicit non-goals (do not build, even if "easy")

Autonomous agent frameworks, multi-agent orchestration, GraphRAG, vector DB,
sophisticated RAG, automatic web-scale paper discovery/download, citation
graphs, automated paper-writing, multi-user SaaS, enterprise auth,
microservices, Kubernetes, queue/worker infrastructure (Celery/RQ/Redis).
