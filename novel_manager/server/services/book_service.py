from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ...db import connect as db_connect
from ..config import is_safe_path, MAX_CONTENT_BYTES


def list_books(
    repo_path: str,
    q: str = "",
    area: str = "all",
    limit: int = 60,
    offset: int = 0,
    sort: str = "updated_at",
) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    conn = _open_db(root)
    if conn is None:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    _ensure_progress_table(root)
    clauses = ["1=1"]
    params: list[Any] = []
    if area and area != "all":
        clauses.append("b.repo_area = ?")
        params.append(area)
    if q:
        like = f"%{q}%"
        clauses.append(
            "(b.file_name LIKE ? OR b.title_norm LIKE ? OR b.author_norm LIKE ?)"
        )
        params.extend([like, like, like])

    try:
        count_sql = f"SELECT COUNT(*) FROM books b WHERE {' AND '.join(clauses)}"
        total = conn.execute(count_sql, params).fetchone()[0]
        order = "b.updated_at DESC" if sort == "updated_at" else "b.title_norm ASC"
        sql = f"""
            SELECT b.*, GROUP_CONCAT(t.name, ', ') AS tags,
                   rp.progress_ratio AS reading_progress,
                   rp.updated_at AS progress_updated_at
            FROM books b
            LEFT JOIN book_tags bt ON bt.book_id = b.id
            LEFT JOIN tags t ON t.id = bt.tag_id
            LEFT JOIN reading_progress rp ON rp.book_id = b.id AND rp.device_id = 'web'
            WHERE {' AND '.join(clauses)}
            GROUP BY b.id
            ORDER BY {order}
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(sql, params + [limit, offset]).fetchall()
        conn.close()

        items = [_row_to_item(dict(r)) for r in rows]
        return {"items": items, "total": total, "limit": limit, "offset": offset}
    except sqlite3.OperationalError:
        conn.close()
        return {"items": [], "total": 0, "limit": limit, "offset": offset}


def get_book_detail(repo_path: str, book_id: int) -> dict[str, Any] | None:
    root = Path(repo_path).expanduser().resolve()
    conn = _open_db(root)
    if conn is None:
        return None
    try:
        row = conn.execute(
            """SELECT b.*, GROUP_CONCAT(t.name, ', ') AS tags
               FROM books b
               LEFT JOIN book_tags bt ON bt.book_id = b.id
               LEFT JOIN tags t ON t.id = bt.tag_id
               WHERE b.id = ?
               GROUP BY b.id""",
            (book_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        d = dict(row)
        return {
            "book_id": d.get("id"),
            "title": d.get("title_norm") or d.get("title_raw") or "",
            "author": d.get("author_norm") or "",
            "file_name": d.get("file_name") or "",
            "area": d.get("repo_area") or "",
            "area_label": _area_label(d.get("repo_area")),
            "current_path": d.get("current_path") or "",
            "file_size": d.get("file_size"),
            "char_count_clean": d.get("char_count_clean"),
            "chapter_count": d.get("chapter_count") or 0,
            "quality_score": d.get("quality_score"),
            "quality_level": d.get("quality_level"),
            "encoding": d.get("encoding"),
            "tags": _split_tags(d.get("tags")),
            "reading_status": d.get("reading_status") or "",
            "group_name": "默认分组",
            "updated_at": d.get("updated_at"),
        }
    except sqlite3.OperationalError:
        conn.close()
        return None


def get_book_content(repo_path: str, book_id: int) -> dict[str, Any] | None:
    root = Path(repo_path).expanduser().resolve()
    detail = get_book_detail(repo_path, book_id)
    if detail is None:
        return None
    path_str = detail.get("current_path") or ""
    if not path_str:
        return {"book_id": book_id, "title": detail["title"], "content": ""}
    file_path = Path(path_str)
    if not is_safe_path(root, file_path):
        return {"book_id": book_id, "title": detail["title"], "content": "", "error": "路径不在仓库范围内"}
    if not file_path.exists():
        return {"book_id": book_id, "title": detail["title"], "content": "", "error": "文件不存在"}
    try:
        from .text_reader import read_text_safely

        result = read_text_safely(file_path, max_bytes=MAX_CONTENT_BYTES)
        return {
            "book_id": book_id,
            "title": detail["title"],
            "content": result["text"],
            "encoding": result["encoding"],
            "decode_warning": result.get("decode_warning"),
        }
    except OSError:
        return {"book_id": book_id, "title": detail["title"], "content": "", "error": "读取文件失败"}


def get_book_chapters(repo_path: str, book_id: int) -> dict[str, Any] | None:
    root = Path(repo_path).expanduser().resolve()
    detail = get_book_detail(repo_path, book_id)
    if detail is None:
        return None
    title = detail["title"]
    ch = _load_chapters_from_db(root, book_id)
    if ch:
        return {"book_id": book_id, "title": title, "chapters": ch}
    content_result = get_book_content(repo_path, book_id)
    text_len = 0
    if content_result and content_result.get("content"):
        try:
            from ...chapter_parser import parse_chapters
            parsed = parse_chapters(content_result["content"])
            text_len = len(content_result["content"])
            if parsed.chapters:
                ch = [{"index": c["chapter_index"], "title": c["title_raw"], "start_offset": c["start_offset"], "end_offset": c["end_offset"]} for c in parsed.chapters]
                return {"book_id": book_id, "title": title, "chapters": ch}
        except Exception:
            pass
    return {"book_id": book_id, "title": title, "chapters": [{"index": 0, "title": "全文", "start_offset": 0, "end_offset": text_len}]}


def _load_chapters_from_db(repo: Path, book_id: int) -> list[dict[str, Any]]:
    try:
        conn = _open_db(repo)
        if conn is None:
            return []
        rows = conn.execute(
            "SELECT chapter_index, title_raw, start_offset, end_offset FROM chapters WHERE book_id = ? ORDER BY chapter_index",
            (book_id,),
        ).fetchall()
        conn.close()
        return [{"index": r["chapter_index"], "title": r["title_raw"], "start_offset": r["start_offset"], "end_offset": r["end_offset"]} for r in rows]
    except Exception:
        return []


def _row_to_item(d: dict[str, Any]) -> dict[str, Any]:
    progress = d.get("reading_progress")
    return {
        "book_id": d.get("id"),
        "title": d.get("title_norm") or d.get("title_raw") or "",
        "author": d.get("author_norm") or "",
        "file_name": d.get("file_name") or "",
        "area": d.get("repo_area") or "",
        "area_label": _area_label(d.get("repo_area")),
        "group_name": "默认分组",
        "quality_score": d.get("quality_score"),
        "chapter_count": d.get("chapter_count") or 0,
        "reading_progress": float(progress) if progress is not None else 0.0,
        "last_read_at": d.get("progress_updated_at") or None,
        "tags": _split_tags(d.get("tags")),
        "status": "normal",
    }


def _ensure_progress_table(repo: Path) -> None:
    try:
        conn = db_connect(repo)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS reading_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                device_id TEXT NOT NULL DEFAULT 'web',
                progress_ratio REAL NOT NULL DEFAULT 0,
                scroll_position INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                UNIQUE(book_id, device_id)
            );
        """)
        conn.commit()
        conn.close()
    except Exception:
        pass


def _open_db(repo: Path) -> sqlite3.Connection | None:
    try:
        return db_connect(repo)
    except Exception:
        return None


def _area_label(area: str | None) -> str:
    m = {"library": "小说库", "incoming": "新下载区", "archive": "归档区", "trash": "废弃区", "review_duplicates": "重复复核区"}
    return m.get(area or "", area or "")


def _split_tags(tags_str: str | None) -> list[str]:
    if not tags_str:
        return []
    return [t.strip() for t in tags_str.split(",") if t.strip()]
