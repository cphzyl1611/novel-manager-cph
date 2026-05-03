from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .utils import ensure_dir, now_ts


DB_RELATIVE = Path("db") / "novel_repo.sqlite"


def db_path(repo: Path) -> Path:
    return repo / DB_RELATIVE


def connect(repo: Path) -> sqlite3.Connection:
    path = db_path(repo)
    ensure_dir(path.parent)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY,
            current_path TEXT NOT NULL,
            original_path TEXT,
            repo_area TEXT,
            file_name TEXT,
            file_size INTEGER,
            mtime REAL,
            raw_sha256 TEXT,
            clean_sha256 TEXT,
            title_raw TEXT,
            title_norm TEXT,
            author_raw TEXT,
            author_norm TEXT,
            encoding TEXT,
            encoding_confidence REAL,
            decode_status TEXT,
            char_count_raw INTEGER,
            char_count_clean INTEGER,
            line_count_raw INTEGER,
            line_count_clean INTEGER,
            chapter_count INTEGER,
            mojibake_rate REAL,
            ad_line_count INTEGER,
            ad_line_rate REAL,
            duplicate_chapter_count INTEGER,
            missing_chapter_count INTEGER,
            chapter_order_error_count INTEGER,
            truncated_risk INTEGER,
            quality_score REAL,
            quality_level TEXT,
            quality_reasons_json TEXT,
            status TEXT,
            reading_status TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_books_raw_sha256 ON books(raw_sha256);
        CREATE INDEX IF NOT EXISTS idx_books_clean_sha256 ON books(clean_sha256);
        CREATE INDEX IF NOT EXISTS idx_books_title_norm ON books(title_norm);
        CREATE INDEX IF NOT EXISTS idx_books_author_norm ON books(author_norm);
        CREATE INDEX IF NOT EXISTS idx_books_repo_area ON books(repo_area);
        CREATE INDEX IF NOT EXISTS idx_books_quality_score ON books(quality_score);

        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY,
            book_id INTEGER,
            chapter_index INTEGER,
            chapter_no INTEGER,
            chapter_type TEXT,
            title_raw TEXT,
            title_norm TEXT,
            start_offset INTEGER,
            end_offset INTEGER,
            char_count INTEGER,
            body_clean_sha256 TEXT,
            is_duplicate_suspect INTEGER,
            is_missing_suspect INTEGER,
            order_status TEXT,
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS scan_errors (
            id INTEGER PRIMARY KEY,
            file_path TEXT,
            repo_area TEXT,
            error_type TEXT,
            error_message TEXT,
            detected_encoding TEXT,
            created_at TEXT,
            resolved INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY,
            operation_type TEXT,
            book_id INTEGER,
            source_path TEXT,
            target_path TEXT,
            raw_sha256_before TEXT,
            raw_sha256_after TEXT,
            status TEXT,
            report_path TEXT,
            reason TEXT,
            created_at TEXT,
            applied_at TEXT
        );

        CREATE TABLE IF NOT EXISTS duplicate_groups (
            id INTEGER PRIMARY KEY,
            group_type TEXT,
            confidence REAL,
            recommended_keep_book_id INTEGER,
            recommended_action TEXT,
            reason_summary TEXT,
            created_at TEXT,
            status TEXT
        );

        CREATE TABLE IF NOT EXISTS duplicate_group_members (
            id INTEGER PRIMARY KEY,
            duplicate_group_id INTEGER,
            book_id INTEGER,
            similarity_score REAL,
            quality_score REAL,
            suggested_role TEXT,
            reason TEXT,
            FOREIGN KEY(duplicate_group_id) REFERENCES duplicate_groups(id) ON DELETE CASCADE,
            FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS work_groups (
            id INTEGER PRIMARY KEY,
            title_norm TEXT,
            author_norm TEXT,
            status TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS book_group_members (
            id INTEGER PRIMARY KEY,
            work_group_id INTEGER,
            book_id INTEGER,
            role TEXT
        );
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            category TEXT,
            description TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS book_tags (
            id INTEGER PRIMARY KEY,
            book_id INTEGER,
            tag_id INTEGER,
            source TEXT,
            confidence REAL,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY,
            name TEXT,
            author_norm TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS series_members (
            id INTEGER PRIMARY KEY,
            series_id INTEGER,
            book_id INTEGER,
            volume_no INTEGER
        );
        CREATE TABLE IF NOT EXISTS update_candidates (
            id INTEGER PRIMARY KEY,
            old_book_id INTEGER,
            new_book_id INTEGER,
            confidence REAL,
            reason TEXT,
            status TEXT,
            created_at TEXT
        );
        """
    )
    from .tag_manager import initialize_default_tags

    initialize_default_tags(conn)
    conn.commit()


def insert_scan_error(
    conn: sqlite3.Connection,
    file_path: str,
    repo_area: str,
    error_type: str,
    error_message: str,
    detected_encoding: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO scan_errors
        (file_path, repo_area, error_type, error_message, detected_encoding, created_at, resolved)
        VALUES (?, ?, ?, ?, ?, ?, 0)
        """,
        (file_path, repo_area, error_type, error_message, detected_encoding, now_ts()),
    )
    conn.commit()


def upsert_book(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    existing = conn.execute(
        "SELECT id, created_at FROM books WHERE current_path = ? ORDER BY id DESC LIMIT 1",
        (data["current_path"],),
    ).fetchone()
    fields = list(data.keys())
    if existing:
        book_id = int(existing["id"])
        data["created_at"] = existing["created_at"]
        data["updated_at"] = now_ts()
        assignments = ", ".join(f"{field} = ?" for field in fields)
        conn.execute(
            f"UPDATE books SET {assignments} WHERE id = ?",
            [data[field] for field in fields] + [book_id],
        )
    else:
        data.setdefault("created_at", now_ts())
        data.setdefault("updated_at", now_ts())
        fields = list(data.keys())
        placeholders = ", ".join("?" for _ in fields)
        conn.execute(
            f"INSERT INTO books ({', '.join(fields)}) VALUES ({placeholders})",
            [data[field] for field in fields],
        )
        book_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    return book_id


def replace_chapters(conn: sqlite3.Connection, book_id: int, chapters: Iterable[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
    for chapter in chapters:
        payload = dict(chapter)
        payload["book_id"] = book_id
        fields = list(payload.keys())
        conn.execute(
            f"INSERT INTO chapters ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
            [payload[field] for field in fields],
        )
    conn.commit()
