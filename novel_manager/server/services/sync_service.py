from __future__ import annotations

import hashlib
import json
import platform
import uuid
from pathlib import Path
from typing import Any

from ...db import connect as db_connect
from .progress_service import get_progress, save_progress, _ensure_table


def _ensure_sync_state_table(conn: Any) -> None:
    """Ensure sync_state table exists for server_revision tracking."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sync_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            server_revision INTEGER NOT NULL DEFAULT 0,
            repo_id TEXT NOT NULL DEFAULT '',
            server_device_id TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sync_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            revision INTEGER NOT NULL,
            change_type TEXT NOT NULL,
            table_name TEXT NOT NULL,
            record_id INTEGER NOT NULL,
            payload TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_sync_changes_revision ON sync_changes(revision);
    """)

    row = conn.execute("SELECT id FROM sync_state WHERE id = 1").fetchone()
    if row is None:
        repo_id = str(uuid.uuid4())[:8]
        device_id = f"desktop-{platform.node() or 'unknown'}-{repo_id}"
        conn.execute(
            "INSERT INTO sync_state (id, server_revision, repo_id, server_device_id) VALUES (1, 0, ?, ?)",
            (repo_id, device_id),
        )
    conn.commit()


def _get_or_create_repo_id(conn: Any) -> str:
    """Get or create the unique repo_id for this repository."""
    row = conn.execute("SELECT repo_id FROM sync_state WHERE id = 1").fetchone()
    if row is None:
        _ensure_sync_state_table(conn)
        row = conn.execute("SELECT repo_id FROM sync_state WHERE id = 1").fetchone()
    return row["repo_id"] if row else ""


def _get_server_revision(conn: Any) -> int:
    """Get current server_revision number."""
    row = conn.execute("SELECT server_revision FROM sync_state WHERE id = 1").fetchone()
    return row["server_revision"] if row else 0


def _increment_server_revision(conn: Any) -> int:
    """Increment server_revision and return new value."""
    conn.execute(
        "UPDATE sync_state SET server_revision = server_revision + 1, updated_at = datetime('now') WHERE id = 1"
    )
    conn.commit()
    return _get_server_revision(conn)


def _record_change(conn: Any, change_type: str, table_name: str, record_id: int, payload: dict | None = None) -> None:
    """Record a change in sync_changes table."""
    revision = _get_server_revision(conn)
    payload_json = json.dumps(payload, ensure_ascii=False) if payload else None
    conn.execute(
        """INSERT INTO sync_changes (revision, change_type, table_name, record_id, payload)
           VALUES (?, ?, ?, ?, ?)""",
        (revision, change_type, table_name, record_id, payload_json),
    )
    conn.commit()


def get_sync_manifest(repo_path: str) -> dict[str, Any]:
    """Get sync manifest with repo metadata.

    Returns:
        {
            "repo_id": "abc123",
            "server_device_id": "desktop-hostname-abc123",
            "server_revision": 42,
            "server_time": "2024-01-15T10:30:00Z",
            "server_version": "1.0.0",
            "library_stats": {"total_books": 100, "total_chapters": 5000}
        }
    """
    root = Path(repo_path).expanduser().resolve()
    conn = db_connect(root)
    _ensure_sync_state_table(conn)

    repo_id = _get_or_create_repo_id(conn)
    server_revision = _get_server_revision(conn)

    row = conn.execute("SELECT server_device_id, updated_at FROM sync_state WHERE id = 1").fetchone()
    server_device_id = row["server_device_id"] if row else ""
    server_time = row["updated_at"] if row else ""

    total_books = conn.execute("SELECT COUNT(*) FROM books WHERE repo_area = 'library' AND (status IS NULL OR status NOT IN ('external_removed', 'ignored_missing'))").fetchone()[0]
    total_chapters = conn.execute("SELECT COALESCE(SUM(chapter_count), 0) FROM books WHERE repo_area = 'library' AND (status IS NULL OR status NOT IN ('external_removed', 'ignored_missing'))").fetchone()[0]

    conn.close()

    return {
        "repo_id": repo_id,
        "server_device_id": server_device_id,
        "server_revision": server_revision,
        "server_time": server_time,
        "server_version": "1.0.0",
        "library_stats": {
            "total_books": total_books,
            "total_chapters": total_chapters,
        },
    }


def get_sync_snapshot(repo_path: str, include_chapters: bool = False) -> dict[str, Any]:
    """Get full library snapshot.

    Args:
        repo_path: Path to repository
        include_chapters: Whether to include chapter details

    Returns:
        {
            "manifest": {...},
            "books": [{...}, ...],
            "chapters": [{...}, ...] if include_chapters
        }
    """
    root = Path(repo_path).expanduser().resolve()
    conn = db_connect(root)
    _ensure_sync_state_table(conn)

    manifest = get_sync_manifest(repo_path)

    books = []
    rows = conn.execute(
        """SELECT id, current_path, title_raw, title_norm, author_raw, author_norm,
                  file_size, raw_sha256, clean_sha256, chapter_count, quality_score,
                  quality_level, status, reading_status, repo_area
           FROM books WHERE repo_area = 'library' AND (status IS NULL OR status NOT IN ('external_removed', 'ignored_missing')) ORDER BY title_norm"""
    ).fetchall()

    for row in rows:
        books.append({
            "id": row["id"],
            "current_path": row["current_path"],
            "title_raw": row["title_raw"],
            "title_norm": row["title_norm"],
            "author_raw": row["author_raw"],
            "author_norm": row["author_norm"],
            "file_size": row["file_size"],
            "raw_sha256": row["raw_sha256"],
            "clean_sha256": row["clean_sha256"],
            "chapter_count": row["chapter_count"],
            "quality_score": row["quality_score"],
            "quality_level": row["quality_level"],
            "status": row["status"],
            "reading_status": row["reading_status"],
        })

    result: dict[str, Any] = {
        "manifest": manifest,
        "books": books,
    }

    if include_chapters:
        chapters = []
        rows = conn.execute(
            """SELECT c.id, c.book_id, c.chapter_index, c.chapter_no, c.title_raw, c.title_norm,
                      c.start_offset, c.end_offset, c.char_count
               FROM chapters c
               JOIN books b ON c.book_id = b.id
               WHERE b.repo_area = 'library' AND (b.status IS NULL OR b.status NOT IN ('external_removed', 'ignored_missing'))
               ORDER BY c.book_id, c.chapter_index"""
        ).fetchall()

        for row in rows:
            chapters.append({
                "id": row["id"],
                "book_id": row["book_id"],
                "chapter_index": row["chapter_index"],
                "chapter_no": row["chapter_no"],
                "title_raw": row["title_raw"],
                "title_norm": row["title_norm"],
                "start_offset": row["start_offset"],
                "end_offset": row["end_offset"],
                "char_count": row["char_count"],
            })
        result["chapters"] = chapters

    conn.close()
    return result


def get_sync_changes(repo_path: str, since_revision: int) -> dict[str, Any]:
    """Get changes since a specific revision.

    Args:
        repo_path: Path to repository
        since_revision: Get changes after this revision

    Returns:
        {
            "manifest": {...},
            "changes": [{...}, ...],
            "has_more": false
        }
    """
    root = Path(repo_path).expanduser().resolve()
    conn = db_connect(root)
    _ensure_sync_state_table(conn)

    manifest = get_sync_manifest(repo_path)

    changes = []
    rows = conn.execute(
        """SELECT id, revision, change_type, table_name, record_id, payload, created_at
           FROM sync_changes
           WHERE revision > ?
           ORDER BY revision ASC
           LIMIT 1000""",
        (since_revision,),
    ).fetchall()

    for row in rows:
        change: dict[str, Any] = {
            "id": row["id"],
            "revision": row["revision"],
            "change_type": row["change_type"],
            "table_name": row["table_name"],
            "record_id": row["record_id"],
            "created_at": row["created_at"],
        }
        if row["payload"]:
            try:
                change["payload"] = json.loads(row["payload"])
            except json.JSONDecodeError:
                change["payload"] = None
        changes.append(change)

    has_more = len(changes) >= 1000

    conn.close()

    return {
        "manifest": manifest,
        "changes": changes,
        "has_more": has_more,
    }


def sync_upload_progress(
    repo_path: str,
    device_id: str,
    progress_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """Upload reading progress from mobile device.

    Args:
        repo_path: Path to repository
        device_id: Unique device identifier
        progress_list: List of progress records to upload

    Returns:
        {
            "ok": true,
            "accepted": 5,
            "rejected": 0,
            "server_revision": 43
        }
    """
    root = Path(repo_path).expanduser().resolve()
    conn = db_connect(root)
    _ensure_sync_state_table(conn)

    accepted = 0
    rejected = 0

    for prog in progress_list:
        book_id = prog.get("book_id")
        if not book_id:
            rejected += 1
            continue

        book = conn.execute("SELECT id FROM books WHERE id = ? AND repo_area = 'library' AND (status IS NULL OR status NOT IN ('external_removed', 'ignored_missing'))", (book_id,)).fetchone()
        if not book:
            rejected += 1
            continue

        progress_ratio = prog.get("progress_ratio", 0)
        scroll_position = prog.get("scroll_position", 0)
        current_chapter_index = prog.get("current_chapter_index", 0)

        result = save_progress(
            repo_path,
            book_id,
            progress_ratio,
            scroll_position,
            device_id,
            current_chapter_index,
        )

        if result.get("ok"):
            accepted += 1
        else:
            rejected += 1

    if accepted > 0:
        _increment_server_revision(conn)

    server_revision = _get_server_revision(conn)
    conn.close()

    return {
        "ok": True,
        "accepted": accepted,
        "rejected": rejected,
        "server_revision": server_revision,
    }


def sync_download_progress(repo_path: str, device_id: str) -> dict[str, Any]:
    """Download reading progress for a device.

    Args:
        repo_path: Path to repository
        device_id: Unique device identifier

    Returns:
        {
            "ok": true,
            "progress": [{...}, ...],
            "server_revision": 42
        }
    """
    root = Path(repo_path).expanduser().resolve()

    # Ensure reading_progress table exists and get connection
    conn = _ensure_table(root)
    _ensure_sync_state_table(conn)

    progress_list = []
    try:
        rows = conn.execute(
            """SELECT rp.book_id, rp.progress_ratio, rp.scroll_position,
                      rp.current_chapter_index, rp.updated_at
               FROM reading_progress rp
               JOIN books b ON rp.book_id = b.id
               WHERE b.repo_area = 'library' AND (b.status IS NULL OR b.status NOT IN ('external_removed', 'ignored_missing')) AND rp.device_id = ?
               ORDER BY rp.updated_at DESC""",
            (device_id,),
        ).fetchall()

        for row in rows:
            progress_list.append({
                "book_id": row[0],
                "progress_ratio": row[1],
                "scroll_position": row[2],
                "current_chapter_index": row[3],
                "updated_at": row[4],
            })
    except Exception:
        pass

    server_revision = _get_server_revision(conn)
    conn.close()

    return {
        "ok": True,
        "progress": progress_list,
        "server_revision": server_revision,
    }


def get_sync_status(repo_path: str) -> dict[str, Any]:
    """Get current sync status (legacy endpoint for backward compatibility)."""
    manifest = get_sync_manifest(repo_path)
    return {
        "server_device_id": manifest["server_device_id"],
        "repo_revision": manifest["server_revision"],
        "connected_clients": 0,
        "last_operation_time": manifest["server_time"],
        "repo_id": manifest["repo_id"],
    }
