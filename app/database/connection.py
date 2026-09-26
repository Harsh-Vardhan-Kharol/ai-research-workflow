"""SQLite connection setup for the local single-operator application."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.config import get_settings


def connect_database(database_path: str | Path | None = None) -> sqlite3.Connection:
    """Open SQLite with foreign keys and WAL enabled."""
    path = Path(database_path) if database_path is not None else get_settings().database_path
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection
