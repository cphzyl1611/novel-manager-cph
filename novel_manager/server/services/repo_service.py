from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ...db import connect as db_connect


def get_repo_status(repo_path: str) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    if not root.exists():
        return {"repo_path": str(root), "initialized": False, "error": "仓库路径不存在"}

    required = ["db", "config", "library"]
    missing = [d for d in required if not (root / d).exists()]
    initialized = root.is_dir() and len(missing) == 0
    if not initialized:
        return {"repo_path": str(root), "initialized": False, "missing_dirs": missing}

    conn = _open_db(root)
    book_count = library_count = incoming_count = archive_count = trash_count = 0
    last_scan_time = None
    if conn:
        try:
            book_count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
            library_count = conn.execute(
                "SELECT COUNT(*) FROM books WHERE repo_area='library'"
            ).fetchone()[0]
            incoming_count = conn.execute(
                "SELECT COUNT(*) FROM books WHERE repo_area='incoming'"
            ).fetchone()[0]
            archive_count = conn.execute(
                "SELECT COUNT(*) FROM books WHERE repo_area LIKE 'archive%'"
            ).fetchone()[0]
            trash_count = conn.execute(
                "SELECT COUNT(*) FROM books WHERE repo_area='trash'"
            ).fetchone()[0]
            row = conn.execute("SELECT MAX(updated_at) FROM books").fetchone()
            last_scan_time = row[0] if row else None
        except sqlite3.OperationalError:
            pass
        finally:
            conn.close()

    return {
        "repo_path": str(root),
        "initialized": True,
        "book_count": book_count,
        "library_count": library_count,
        "incoming_count": incoming_count,
        "archive_count": archive_count,
        "trash_count": trash_count,
        "last_scan_time": last_scan_time,
        "health": {"errors": 0, "warnings": 0},
    }


def _open_db(repo: Path) -> sqlite3.Connection | None:
    try:
        return db_connect(repo)
    except Exception:
        return None
