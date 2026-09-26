# Tech Stack

| Layer | Choice | Why | Cost |
|---|---|---|---|
| Backend framework | FastAPI | Async support, automatic OpenAPI, Pydantic-native | Free |
| PDF processing | PyMuPDF (`fitz`) | Reliable page-level text extraction, fast, permissive license | Free |
| Multipart upload parsing | `python-multipart` | Required by FastAPI to accept the documented multipart PDF upload | Free |
| Schema validation | Pydantic v2 | Already FastAPI-native; strict typed validation of AI output | Free |
| Database | SQLite (via SQLAlchemy Core or lightweight repository, WAL mode) | Zero-ops, sufficient for single-user MVP scale; no compelling reason to change | Free |
| Evidence similarity | `rapidfuzz` | Fast fuzzy string matching for evidence validation; no ML training needed | Free |
| AI provider (default) | Hosted API (Claude or GPT-family) via structured tool-calling | Materially more reliable JSON conformance than small local models — matters for a graded demo | Pay-per-call, expect low single-digit dollars for full dev+demo cycle |
| AI provider (optional/future) | Local model via Ollama (e.g., Llama 3.1 8B) | Free, offline | Free, but degraded structured-output reliability — document, don't default to it |
| Frontend | Streamlit | Fast to build, sufficient for dashboard/comparison/review UI within the time budget | Free |
| Testing | pytest | Standard, works for unit/integration/e2e | Free |
| Logging | Python `logging` (structured, JSON-formatted lines) | No extra infra needed | Free |

## Explicitly rejected for MVP (with reason)

- **React frontend** — would add build tooling, API-contract duplication, and
  days of UI work for a solo 7–14 day project with no requirement for
  multi-user or highly custom interactivity. Streamlit is sufficient for every
  required page (upload, papers, detail, comparison, analytics, review).
  Document as a legitimate future upgrade if the project continues past MVP.
- **Vector database / embeddings** — no RAG requirement; structured relational
  data is the knowledge layer.
- **Celery/RQ/Redis job queue** — single-user, low-volume processing does not
  need distributed workers; FastAPI `BackgroundTasks` is sufficient.
- **PostgreSQL** — no concurrency/scale requirement that SQLite can't meet at
  MVP volumes; switching is a documented future option, not a current need.
- **Authentication framework** — single local operator; no multi-user
  requirement in scope.

## Environment variables (see `ENVIRONMENT_SETUP.md` for full list)

`AI_PROVIDER`, `AI_API_KEY`, `AI_MODEL_NAME`, `DATABASE_PATH`,
`MAX_UPLOAD_SIZE_MB`, `LOG_LEVEL`.
