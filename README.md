# ResearchFlow AI

Local research-paper extraction and human review tool. The Streamlit UI talks
to FastAPI over HTTP; only the backend accesses SQLite.

## Run locally

Install dependencies and configure `.env` as described in
[`docs/ENVIRONMENT_SETUP.md`](docs/ENVIRONMENT_SETUP.md). Start each service
in a separate terminal from the repository root:

```bash
uvicorn app.main:app --reload --port 8000
```

```bash
streamlit run frontend/app.py
```

The UI defaults to `http://localhost:8000`. Set `RESEARCHFLOW_API_URL` in the
Streamlit terminal to point it at a different FastAPI base URL.
