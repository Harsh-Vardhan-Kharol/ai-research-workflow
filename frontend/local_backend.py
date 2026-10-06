"""Start the bundled FastAPI service when Streamlit is the only process."""

from __future__ import annotations

import os
import socket
import threading
import time

import streamlit as st


def _port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        return probe.connect_ex((host, port)) == 0


@st.cache_resource(show_spinner=False)
def ensure_backend() -> str:
    """Return the configured API URL, starting the bundled API when needed.

    Streamlit Cloud runs the Streamlit script as its application process and
    does not run a second ``uvicorn`` command. In that case the bundled API is
    started in a daemon thread. A separately configured API URL always wins.
    """
    configured_url = os.getenv("RESEARCHFLOW_API_URL")
    if configured_url:
        return configured_url.rstrip("/")

    host = "127.0.0.1"
    port = int(os.getenv("RESEARCHFLOW_API_PORT", "8000"))
    base_url = f"http://{host}:{port}"
    if _port_is_open(host, port):
        return base_url

    import uvicorn
    from app.main import app

    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, name="researchflow-api", daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _port_is_open(host, port):
            return base_url
        if not thread.is_alive():
            break
        time.sleep(0.1)

    raise RuntimeError("The bundled FastAPI backend could not be started.")
