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

        CREATE TABLE IF NOT EXISTS ai_extraction_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            group_name TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED')),
            validated_payload TEXT,
            section_detected INTEGER NOT NULL CHECK (section_detected IN (0, 1)),
            truncated INTEGER NOT NULL CHECK (truncated IN (0, 1)),
            failure_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (paper_id, group_name),
            CHECK ((status = 'SUCCEEDED' AND validated_payload IS NOT NULL
                    AND failure_code IS NULL) OR
                   (status = 'FAILED' AND validated_payload IS NULL
                    AND failure_code IS NOT NULL))
        );

        CREATE INDEX IF NOT EXISTS idx_ai_extraction_groups_paper_id
            ON ai_extraction_groups(paper_id);

        CREATE TABLE IF NOT EXISTS extractions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            group_name TEXT NOT NULL,
            field_name TEXT NOT NULL,
            item_index INTEGER NOT NULL CHECK (item_index >= 0),
            field_value TEXT NOT NULL,
            proposed_source_text TEXT,
            proposed_page INTEGER,
            proposed_section TEXT,
            confidence_score REAL,
            confidence_level TEXT,
            status TEXT NOT NULL CHECK (status IN (
                'EXTRACTED', 'PENDING_REVIEW', 'ACCEPTED', 'EDITED', 'REJECTED'
            )),
            section_detected INTEGER NOT NULL CHECK (section_detected IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (paper_id, group_name, field_name, item_index)
        );

        CREATE INDEX IF NOT EXISTS idx_extractions_paper_id ON extractions(paper_id);
        CREATE INDEX IF NOT EXISTS idx_extractions_status ON extractions(status);

        CREATE TABLE IF NOT EXISTS evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            extraction_id INTEGER NOT NULL REFERENCES extractions(id) ON DELETE CASCADE,
            page_number INTEGER,
            section_name TEXT,
            source_text TEXT NOT NULL,
            evidence_score REAL NOT NULL CHECK (
                evidence_score >= 0 AND evidence_score <= 1
            ),
            page_corrected INTEGER NOT NULL CHECK (page_corrected IN (0, 1)),
            match_status TEXT NOT NULL CHECK (match_status IN (
                'MATCHED', 'WEAK', 'UNAVAILABLE', 'FAILED'
            )),
            failure_code TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (extraction_id)
        );

        CREATE INDEX IF NOT EXISTS idx_evidence_extraction_id
            ON evidence(extraction_id);
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


def save_extraction_group(
    connection: sqlite3.Connection,
    paper_id: int,
    group_name: str,
    status: str,
    validated_payload: str | None,
    section_detected: bool,
    truncated: bool,
    failure_code: str | None = None,
) -> None:
    """Atomically upsert one group; only schema-validated JSON may succeed."""
    with connection:
        connection.execute(
            """INSERT INTO ai_extraction_groups
               (paper_id, group_name, status, validated_payload, section_detected,
                truncated, failure_code, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(paper_id, group_name) DO UPDATE SET
                 status = excluded.status,
                 validated_payload = excluded.validated_payload,
                 section_detected = excluded.section_detected,
                 truncated = excluded.truncated,
                 failure_code = excluded.failure_code,
                 updated_at = excluded.updated_at""",
            (
                paper_id,
                group_name,
                status,
                validated_payload,
                int(section_detected),
                int(truncated),
                failure_code,
                _now(),
                _now(),
            ),
        )


def get_extraction_groups(
    connection: sqlite3.Connection, paper_id: int
) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """SELECT group_name, status, validated_payload, section_detected,
                      truncated, failure_code, created_at, updated_at
               FROM ai_extraction_groups WHERE paper_id = ? ORDER BY group_name""",
            (paper_id,),
        ).fetchall()
    )


def replace_extraction_group_results(
    connection: sqlite3.Connection,
    paper_id: int,
    group_name: str,
    items: Iterable[dict[str, object]],
) -> None:
    """Atomically replace one group's claims and its independent evidence rows."""
    now = _now()
    with connection:
        connection.execute(
            "DELETE FROM extractions WHERE paper_id = ? AND group_name = ?",
            (paper_id, group_name),
        )
        for item in items:
            cursor = connection.execute(
                """INSERT INTO extractions
                   (paper_id, group_name, field_name, item_index, field_value,
                    proposed_source_text, proposed_page, proposed_section,
                    confidence_score, confidence_level, status, section_detected,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'EXTRACTED', ?, ?, ?)""",
                (
                    paper_id,
                    group_name,
                    item["field_name"],
                    item["item_index"],
                    item["field_value"],
                    item["proposed_source_text"],
                    item["proposed_page"],
                    item["proposed_section"],
                    int(bool(item["section_detected"])),
                    now,
                    now,
                ),
            )
            extraction_id = int(cursor.lastrowid)
            result = item["evidence"]
            if not isinstance(result, dict):
                raise TypeError("evidence result must be a mapping")
            connection.execute(
                """INSERT INTO evidence
                   (extraction_id, page_number, section_name, source_text,
                    evidence_score, page_corrected, match_status, failure_code,
                    created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    extraction_id,
                    result["page_number"],
                    result["section_name"],
                    result["source_text"],
                    result["evidence_score"],
                    int(bool(result["page_corrected"])),
                    result["match_status"],
                    result["failure_code"],
                    now,
                ),
            )


def get_extractions_for_paper(
    connection: sqlite3.Connection, paper_id: int
) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """SELECT id, group_name, field_name, item_index, field_value,
                      proposed_source_text, proposed_page, proposed_section,
                      confidence_score, confidence_level, status, section_detected
               FROM extractions WHERE paper_id = ? ORDER BY id""",
            (paper_id,),
        ).fetchall()
    )


def get_extraction_with_evidence(
    connection: sqlite3.Connection, extraction_id: int
) -> sqlite3.Row | None:
    return connection.execute(
        """SELECT x.id, x.paper_id, x.group_name, x.field_name, x.item_index,
                  x.field_value, x.proposed_source_text, x.proposed_page,
                  x.proposed_section, x.status, e.page_number, e.section_name,
                  e.source_text AS verified_source_text, e.evidence_score,
                  e.page_corrected, e.match_status, e.failure_code
           FROM extractions AS x LEFT JOIN evidence AS e ON e.extraction_id = x.id
           WHERE x.id = ?""",
        (extraction_id,),
    ).fetchone()
