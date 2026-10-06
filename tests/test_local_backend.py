"""Tests for the single-process Streamlit deployment path."""

from frontend.local_backend import ensure_backend


def test_configured_backend_url_is_used(monkeypatch):
    monkeypatch.setenv("RESEARCHFLOW_API_URL", "https://api.example.test/")
    ensure_backend.clear()

    assert ensure_backend() == "https://api.example.test"

    ensure_backend.clear()
