"""Start the bundled FastAPI service when Streamlit is the only process."""

from __future__ import annotations

import os
import socket
import threading
import time
from typing import Any

import streamlit as st


def _port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        return probe.connect_ex((host, port)) == 0


def _load_streamlit_secrets() -> None:
    """Expose deployment secrets to the bundled backend configuration.

    Streamlit Cloud stores values in ``st.secrets`` rather than exporting
    them as process environment variables. The FastAPI configuration is
    intentionally framework-agnostic and reads environment variables, so
    bridge only known settings before importing ``app.main``.
    """
    try:
        secrets = st.secrets
        for name in (
            "AI_PROVIDER",
            "AI_API_KEY",
            "AI_MODEL_NAME",
            "AI_BASE_URL",
            "AI_TIMEOUT_SECONDS",
            "DATABASE_PATH",
            "MAX_UPLOAD_SIZE_MB",
            "MAX_AI_RETRIES",
            "MAX_EXTRACTION_CHARS",
            "MIN_EVIDENCE_THRESHOLD",
            "LOG_LEVEL",
        ):
            if name not in os.environ and name in secrets:
                os.environ[name] = str(secrets[name])
    except Exception:
        # Local runs without a secrets file are expected and use .env/defaults.
        return


def _start_server(host: str, port: int) -> tuple[Any, str] | None:
    """Start Uvicorn and return its bound URL once application startup finished."""
    _load_streamlit_secrets()
    import uvicorn
    from app.main import app

    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, name="researchflow-api", daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if server.started:
            sockets = [sock for srv in (server.servers or []) for sock in srv.sockets]
            if sockets:
                bound_port = int(sockets[0].getsockname()[1])
                return server, f"http://{host}:{bound_port}"
            break
        if not thread.is_alive():
            return None
        time.sleep(0.1)
    return None


@st.cache_resource(show_spinner=False)
def ensure_backend() -> str:
    """Return the configured API URL, starting the bundled API when needed.

    Streamlit Cloud runs the Streamlit script as its application process and
    does not run a second ``uvicorn`` command. In that case the bundled API is
    started in a daemon thread. A separately configured API URL always wins.
    """
    configured_url = os.getenv("RESEARCHFLOW_API_URL", "").strip()
    if configured_url:
        return configured_url.rstrip("/")

    host = "127.0.0.1"
    try:
        configured_port = int(os.getenv("RESEARCHFLOW_API_PORT", "8000"))
    except ValueError as exc:
        raise ValueError("RESEARCHFLOW_API_PORT must be an integer") from exc
    if not 0 <= configured_port <= 65535:
        raise ValueError("RESEARCHFLOW_API_PORT must be between 0 and 65535")

    # Keep the documented port when it is available. Port 0 asks the OS for a
    # free ephemeral port, which is useful on managed hosts where 8000 may be
    # reserved by another process.
    if configured_port and _port_is_open(host, configured_port):
        return f"http://{host}:{configured_port}"
    started = _start_server(host, configured_port)
    if started is not None:
        return started[1]

    # A collision/race on the preferred port should not take down the UI.
    # Uvicorn reports the actual ephemeral port through its listening socket.
    if configured_port:
        started = _start_server(host, 0)
        if started is not None:
            return started[1]

    raise RuntimeError("The bundled FastAPI backend could not be started.")
