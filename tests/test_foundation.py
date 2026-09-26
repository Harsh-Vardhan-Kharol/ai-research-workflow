"""Tests for configuration, logging, database, and API startup foundations."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace

import app.main as main_module
from app.core.config import get_settings
from app.core.logging import JsonFormatter
from app.database.connection import connect_database
from app.main import app


def test_database_connection_enables_wal_and_foreign_keys(tmp_path) -> None:
    connection = connect_database(tmp_path / "foundation.db")
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("SELECT 1").fetchone()[0] == 1
    finally:
        connection.close()


def test_json_formatter_includes_structured_context() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 10, "started", (), None)
    record.paper_id = 12

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "started"
    assert payload["paper_id"] == 12
    assert payload["level"] == "INFO"


def test_configuration_loads_environment_values(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "configured.db"))
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "10")

    settings = get_settings()

    assert settings.ai_provider == "mock"
    assert settings.database_path == tmp_path / "configured.db"
    assert settings.max_upload_size_mb == 10


def test_application_startup_connects_database(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        main_module,
        "settings",
        replace(main_module.settings, database_path=tmp_path / "startup.db"),
    )

    async def run_lifespan() -> None:
        async with main_module.lifespan(main_module.app):
            assert (tmp_path / "startup.db").exists()

    asyncio.run(run_lifespan())
