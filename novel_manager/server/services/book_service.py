from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ...db import connect as db_connect
from ..config import is_safe_path, MAX_CONTENT_BYTES


def _is_current_library_book(root: Path, book: dict[str, Any]) -> bool:
    """Check if a book record corresponds to a real, readable library TXT."""
    if book.get("repo_area") != "library":
        return False
    status = book.get("status") or ""
    if status in ("external_removed", "ignored_missing"):
        return False
    current_path = book.get("current_path")
    if not current_path:
        return False
    try:
        p = Path(current_path).resolve()
        if not p.exists():
            return False
        if p.suffix.lower() != ".txt":
            return False
        library_dir = (root / "library").resolve()
        p.relative_to(library_dir)
    except (ValueError, OSError):
        return False
    return True


def list_books(
    repo_path: str,
    q: str = "",
    area: str = "all",
    limit: int = 60,
    offset: int = 0,
    sort: str = "updated_at",
    include_removed: bool = False,
    page: int = 0,
    page_size: int = 0,
    validate_paths: bool = True,
) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    conn = _open_db(root)
    if conn is None:
        base = {"items": [], "books": []}
        if page_size:
            base["pagination"] = {"page": page, "page_size": page_size, "total": 0, "total_pages": 0, "has_prev": False, "has_next": False}
        return base

    _ensure_progress_table(root)
    clauses: list[str] = []
    params: list[Any] = []
    if area and area != "all":
        clauses.append("b.repo_area = ?")
        params.append(area)
    else:
        clauses.append("b.repo_area = 'library'")
    if q:
        like = f"%{q}%"
        clauses.append(
            "(b.file_name LIKE ? OR b.title_norm LIKE ? OR b.author_norm LIKE ?)"
        )
        params.extend([like, like, like])
    if not include_removed:
        clauses.append("(b.status IS NULL OR b.status NOT IN ('external_removed', 'ignored_missing'))")

    try:
        if sort == "title":
            order = "b.title_norm ASC"
        elif sort == "updated_at":
            order = "b.updated_at DESC"
        else:
            # Default: recent_read — books with recent progress first
            order = """CASE WHEN rpl.latest_read_at IS NULL THEN 1 ELSE 0 END ASC,
                       rpl.latest_read_at DESC,
                       b.updated_at DESC,
                       b.id DESC"""

        sql = f"""
            SELECT b.*, GROUP_CONCAT(t.name, ', ') AS tags,
                   rp.progress_ratio AS reading_progress,
                   rp.updated_at AS progress_updated_at,
                   rpl.latest_read_at AS latest_read_at
            FROM books b
            LEFT JOIN book_tags bt ON bt.book_id = b.id
            LEFT JOIN tags t ON t.id = bt.tag_id
            LEFT JOIN reading_progress rp ON rp.book_id = b.id AND rp.device_id = 'web'
            LEFT JOIN (
                SELECT book_id, MAX(updated_at) AS latest_read_at
                FROM reading_progress
                GROUP BY book_id
            ) rpl ON rpl.book_id = b.id
            WHERE {' AND '.join(clauses)}
            GROUP BY b.id
            ORDER BY {order}
        """
        rows = conn.execute(sql, params).fetchall()
        conn.close()

        # Python-side path validation
        if validate_paths and area == "all" and not include_removed:
            valid_rows = [r for r in rows if _is_current_library_book(root, dict(r))]
        else:
            valid_rows = rows

        total = len(valid_rows)

        # Pagination
        if page_size and page >= 1:
            start = (page - 1) * page_size
            page_rows = valid_rows[start : start + page_size]
            total_pages = max(1, (total + page_size - 1) // page_size)
        elif offset or limit:
            page_rows = valid_rows[offset : offset + limit]
            total_pages = 0
            page_size = 0
            page = 0
        else:
            page_rows = valid_rows
            total_pages = 0
            page_size = 0
            page = 0

        items = [_row_to_item(dict(r)) for r in page_rows]
        result: dict[str, Any] = {
            "items": items,
            "books": items,
            "total": total,
        }
        if page_size:
            result["limit"] = page_size
            result["offset"] = (page - 1) * page_size
            result["pagination"] = {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
                "has_prev": page > 1,
                "has_next": page < total_pages,
            }
        else:
            result["limit"] = limit
            result["offset"] = offset

        return result
    except sqlite3.OperationalError:
        conn.close()
        return {"items": [], "books": [], "total": 0}


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
        "latest_read_at": d.get("latest_read_at") or None,
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
