from __future__ import annotations

from pathlib import Path
from typing import Any

from ...db import connect as db_connect


def _ensure_table(repo: Path) -> Any:
    conn = db_connect(repo)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reading_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            device_id TEXT NOT NULL DEFAULT 'web',
            progress_ratio REAL NOT NULL DEFAULT 0,
            scroll_position INTEGER NOT NULL DEFAULT 0,
            current_chapter_index INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
            UNIQUE(book_id, device_id)
        );
    """)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(reading_progress)").fetchall()]
    if "current_chapter_index" not in cols:
        conn.execute("ALTER TABLE reading_progress ADD COLUMN current_chapter_index INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    return conn


def get_progress(repo_path: str, book_id: int, device_id: str = "web") -> dict[str, Any] | None:
    root = Path(repo_path).expanduser().resolve()
    try:
        conn = _ensure_table(root)
    except Exception:
        return None
    row = conn.execute(
        "SELECT * FROM reading_progress WHERE book_id = ? AND device_id = ?",
        (book_id, device_id),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    return {
        "book_id": d["book_id"],
        "progress_ratio": d["progress_ratio"],
        "scroll_position": d["scroll_position"],
        "current_chapter_index": d.get("current_chapter_index", 0),
        "updated_at": d["updated_at"],
        "device_id": d["device_id"],
    }


def save_progress(
    repo_path: str,
    book_id: int,
    progress_ratio: float,
    scroll_position: int = 0,
    device_id: str = "web",
    current_chapter_index: int = 0,
) -> dict[str, Any]:
    ratio = max(0.0, min(1.0, float(progress_ratio)))
    pos = max(0, int(scroll_position))
    ch_idx = max(0, int(current_chapter_index))
    root = Path(repo_path).expanduser().resolve()
    try:
        conn = _ensure_table(root)
    except Exception:
        return {"ok": False, "error": "无法连接数据库"}
    book = conn.execute("SELECT id FROM books WHERE id = ?", (book_id,)).fetchone()
    if book is None:
        conn.close()
        return {"ok": False, "error": "小说不存在"}
    conn.execute(
        """INSERT INTO reading_progress (book_id, device_id, progress_ratio, scroll_position, current_chapter_index, updated_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(book_id, device_id) DO UPDATE SET
           progress_ratio = excluded.progress_ratio,
           scroll_position = excluded.scroll_position,
           current_chapter_index = excluded.current_chapter_index,
           updated_at = datetime('now')""",
        (book_id, device_id, ratio, pos, ch_idx),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "book_id": book_id, "progress_ratio": ratio, "scroll_position": pos, "current_chapter_index": ch_idx}


def copy_reading_progress_for_replacement(conn, old_book_id: int, new_book_id: int) -> dict[str, Any]:
    """Copy reading progress from old book to new book after version replacement.

    If new book already has progress for a device_id, keep the newer one.
    Never delete old book's progress records.
    """
    try:
        old_rows = conn.execute(
            "SELECT device_id, progress_ratio, scroll_position, current_chapter_index, updated_at FROM reading_progress WHERE book_id = ?",
            (old_book_id,),
        ).fetchall()
    except Exception:
        return {"copied": 0, "skipped": 0, "devices": []}

    if not old_rows:
        return {"copied": 0, "skipped": 0, "devices": []}

    copied = 0
    skipped = 0
    devices = []

    for row in old_rows:
        device_id = row[0]
        progress_ratio = row[1]
        scroll_position = row[2]
        current_chapter_index = row[3]
        old_updated_at = row[4]

        existing = conn.execute(
            "SELECT updated_at FROM reading_progress WHERE book_id = ? AND device_id = ?",
            (new_book_id, device_id),
        ).fetchone()

        if existing:
            new_updated_at = existing[0]
            if old_updated_at and new_updated_at and old_updated_at > new_updated_at:
                conn.execute(
                    """UPDATE reading_progress SET progress_ratio = ?, scroll_position = ?, current_chapter_index = ?, updated_at = ?
                       WHERE book_id = ? AND device_id = ?""",
                    (progress_ratio, scroll_position, current_chapter_index, old_updated_at, new_book_id, device_id),
                )
                copied += 1
                devices.append(device_id)
            else:
                skipped += 1
        else:
            conn.execute(
                """INSERT INTO reading_progress (book_id, device_id, progress_ratio, scroll_position, current_chapter_index, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (new_book_id, device_id, progress_ratio, scroll_position, current_chapter_index, old_updated_at),
            )
            copied += 1
            devices.append(device_id)

    return {"copied": copied, "skipped": skipped, "devices": devices}
