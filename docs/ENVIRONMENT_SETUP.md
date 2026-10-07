# Environment Setup

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `AI_PROVIDER` | yes | `hosted` | `hosted` or `mock` (tests/local demonstration) |
| `AI_API_KEY` | yes if `AI_PROVIDER=hosted` | — | Hosted provider API key; never commit this |
| `AI_MODEL_NAME` | yes if `AI_PROVIDER=hosted` | — | Model identifier passed to the adapter |
| `AI_BASE_URL` | yes if `AI_PROVIDER=hosted` | — | Configured OpenAI-compatible chat-completions endpoint |
| `AI_TIMEOUT_SECONDS` | no | `30` | Per-request timeout |
| `DATABASE_PATH` | no | `./data/researchflow.db` | SQLite file path |
| `MAX_UPLOAD_SIZE_MB` | no | `25` | Upload size cap |
| `MAX_AI_RETRIES` | no | `2` | Retry cap for malformed/timeout AI calls |
| `MAX_EXTRACTION_CHARS` | no | `12000` | Chunking cap per extraction call |
| `MIN_EVIDENCE_THRESHOLD` | no | `0.35` | Below this, evidence_score contributes 0 to confidence |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` for full-content logging (see `SECURITY.md` caveat) |
| `RESEARCHFLOW_API_URL` | no | `http://localhost:8000` | FastAPI base URL used by Streamlit |

`.env.example` should list all of the above with placeholder/default values;
`.env` itself must be in `.gitignore`. No vendor, model, endpoint, or key is
hardcoded. Mock mode makes no hosted request.

## Local install & run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in AI_API_KEY
uvicorn app.main:app --reload --port 8000
streamlit run frontend/app.py
```

Run the two server commands in separate terminals. Set
`RESEARCHFLOW_API_URL` in the frontend terminal to point it at another API
address, for example `RESEARCHFLOW_API_URL=http://127.0.0.1:8000`.

## Deployment

The Streamlit entrypoint starts the bundled FastAPI service automatically when
`RESEARCHFLOW_API_URL` is not set. This supports a single-process deployment
such as Streamlit Cloud. For a separately hosted backend, set
`RESEARCHFLOW_API_URL` to its base URL; the frontend will use that service and
will not start a local one.

For Streamlit Cloud, add the AI settings under **Settings → Secrets** using
TOML keys with these names (the bundled backend loads them automatically):

```toml
AI_PROVIDER = "hosted"
AI_API_KEY = "..."
AI_MODEL_NAME = "openai/gpt-oss-120b"
AI_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"
```

The sidebar API-key field is only a session UI placeholder; it does not replace
the backend deployment secrets.
