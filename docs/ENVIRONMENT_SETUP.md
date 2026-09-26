# Environment Setup

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `AI_PROVIDER` | yes | `hosted` | `hosted` or `local` (Ollama) or `mock` (tests) |
| `AI_API_KEY` | yes if `AI_PROVIDER=hosted` | — | Hosted provider API key; never commit this |
| `AI_MODEL_NAME` | yes | provider-specific default | Model identifier passed to the adapter |
| `DATABASE_PATH` | no | `./data/researchflow.db` | SQLite file path |
| `MAX_UPLOAD_SIZE_MB` | no | `25` | Upload size cap |
| `MAX_AI_RETRIES` | no | `2` | Retry cap for malformed/timeout AI calls |
| `MAX_EXTRACTION_CHARS` | no | `12000` | Chunking cap per extraction call |
| `MIN_EVIDENCE_THRESHOLD` | no | `0.35` | Below this, evidence_score contributes 0 to confidence |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` for full-content logging (see `SECURITY.md` caveat) |

`.env.example` should list all of the above with placeholder/default
values; `.env` itself must be in `.gitignore`.

## Local install & run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in AI_API_KEY
uvicorn app.main:app --reload --port 8000
streamlit run frontend/app.py
```

## Deployment

Out of scope for MVP. This is a local demo tool — no deployment target
(cloud, Docker, etc.) is required. If deployment is later requested, it
should be documented as new scope, not assumed here.
