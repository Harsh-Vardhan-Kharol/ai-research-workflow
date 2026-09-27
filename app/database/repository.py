"""SQL access for paper records, page text, and detected sections."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Iterable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Create the documented paper and page tables if they do not exist."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            abstract TEXT,
            authors TEXT,
            publication_year INTEGER,
            source TEXT,
            file_name TEXT NOT NULL,
            file_hash TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK (status IN (
                'UPLOADED', 'EXTRACTING_TEXT', 'TEXT_EXTRACTED',
                'DETECTING_SECTIONS', 'EXTRACTING_AI', 'VALIDATING',
                'MAPPING_EVIDENCE', 'SCORING_CONFIDENCE', 'READY', 'FAILED'
            )),
            failure_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL CHECK (page_number > 0),
            text TEXT NOT NULL,
            UNIQUE (paper_id, page_number)
        );

        CREATE INDEX IF NOT EXISTS idx_paper_pages_paper_id
            ON paper_pages(paper_id);

        CREATE TABLE IF NOT EXISTS paper_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            section_name TEXT NOT NULL,
            start_page INTEGER NOT NULL CHECK (start_page > 0),
            end_page INTEGER NOT NULL CHECK (end_page >= start_page),
            content TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_paper_sections_paper_id
            ON paper_sections(paper_id);
        """
    )
    connection.commit()


def find_paper_by_hash(
    connection: sqlite3.Connection, file_hash: str
) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT id, file_name, file_hash, status FROM papers WHERE file_hash = ?",
        (file_hash,),
    ).fetchone()


def create_paper(
    connection: sqlite3.Connection, file_name: str, file_hash: str
) -> int:
    now = _now()
    cursor = connection.execute(
        """INSERT INTO papers
           (source, file_name, file_hash, status, created_at, updated_at)
           VALUES ('upload', ?, ?, 'UPLOADED', ?, ?)""",
        (file_name, file_hash, now, now),
    )
    connection.commit()
    return int(cursor.lastrowid)


def get_paper(connection: sqlite3.Connection, paper_id: int) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM papers WHERE id = ?", (paper_id,)
    ).fetchone()


def set_paper_status(
    connection: sqlite3.Connection,
    paper_id: int,
    status: str,
    failure_reason: str | None = None,
) -> None:
    cursor = connection.execute(
        """UPDATE papers SET status = ?, failure_reason = ?, updated_at = ?
           WHERE id = ?""",
        (status, failure_reason, _now(), paper_id),
    )
    connection.commit()
    if cursor.rowcount == 0:
        raise LookupError(f"Paper {paper_id} does not exist")


def save_pages_and_status(
    connection: sqlite3.Connection,
    paper_id: int,
    pages: Iterable[tuple[int, str]],
) -> None:
    """Replace a paper's pages and mark the completed text-extraction stage."""
    with connection:
        connection.execute("DELETE FROM paper_pages WHERE paper_id = ?", (paper_id,))
        connection.executemany(
            "INSERT INTO paper_pages (paper_id, page_number, text) VALUES (?, ?, ?)",
            ((paper_id, page_number, text) for page_number, text in pages),
        )
        cursor = connection.execute(
            """UPDATE papers SET status = 'TEXT_EXTRACTED', failure_reason = NULL,
               updated_at = ? WHERE id = ?""",
            (_now(), paper_id),
        )
        if cursor.rowcount == 0:
            raise LookupError(f"Paper {paper_id} does not exist")


def get_paper_pages(
    connection: sqlite3.Connection, paper_id: int
) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """SELECT page_number, text FROM paper_pages
               WHERE paper_id = ? ORDER BY page_number""",
            (paper_id,),
        ).fetchall()
    )


def save_sections_and_status(
    connection: sqlite3.Connection,
    paper_id: int,
    sections: Iterable[tuple[str, int, int, str]],
) -> None:
    """Atomically replace detected sections and mark detection complete."""
    with connection:
        connection.execute("DELETE FROM paper_sections WHERE paper_id = ?", (paper_id,))
        connection.executemany(
            """INSERT INTO paper_sections
               (paper_id, section_name, start_page, end_page, content)
               VALUES (?, ?, ?, ?, ?)""",
            (
                (paper_id, name, start, end, content)
                for name, start, end, content in sections
            ),
        )
        cursor = connection.execute(
            """UPDATE papers SET status = 'DETECTING_SECTIONS', failure_reason = NULL,
               updated_at = ? WHERE id = ?""",
            (_now(), paper_id),
        )
        if cursor.rowcount == 0:
            raise LookupError(f"Paper {paper_id} does not exist")


def get_paper_sections(
    connection: sqlite3.Connection, paper_id: int
) -> list[sqlite3.Row]:
    """Return sections in document order, retaining the schema fields."""
    return list(
        connection.execute(
            """SELECT section_name, start_page, end_page, content
               FROM paper_sections WHERE paper_id = ?
               ORDER BY start_page, id""",
            (paper_id,),
        ).fetchall()
    )
