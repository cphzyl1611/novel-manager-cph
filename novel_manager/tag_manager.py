from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any

from .operations import log_operation
from .utils import now_ts

VALID_READING_STATUSES = {"未读", "正在读", "已读", "弃书", "想重读", "待整理"}
VALID_TAG_CATEGORIES = {"genre", "status", "quality", "source", "custom"}

DEFAULT_TAGS: list[tuple[str, str, str]] = [
    ("玄幻", "genre", "题材：玄幻"),
    ("仙侠", "genre", "题材：仙侠"),
    ("都市", "genre", "题材：都市"),
    ("科幻", "genre", "题材：科幻"),
    ("历史", "genre", "题材：历史"),
    ("悬疑", "genre", "题材：悬疑"),
    ("同人", "genre", "题材：同人"),
    ("轻小说", "genre", "题材：轻小说"),
    ("游戏", "genre", "题材：游戏"),
    ("无限流", "genre", "题材：无限流"),
    ("末世", "genre", "题材：末世"),
    ("武侠", "genre", "题材：武侠"),
    ("奇幻", "genre", "题材：奇幻"),
    ("现实", "genre", "题材：现实"),
    ("完本", "status", "状态：完本"),
    ("连载", "status", "状态：连载"),
    ("未完结", "status", "状态：未完结"),
    ("太监", "status", "状态：太监"),
    ("短篇", "status", "状态：短篇"),
    ("长篇", "status", "状态：长篇"),
    ("精校", "quality", "质量：精校"),
    ("待整理", "quality", "质量：待整理"),
    ("疑似重复", "quality", "质量：疑似重复"),
    ("疑似缺章", "quality", "质量：疑似缺章"),
    ("疑似乱码", "quality", "质量：疑似乱码"),
    ("广告较多", "quality", "质量：广告较多"),
    ("章节异常", "quality", "质量：章节异常"),
    ("低质量", "quality", "质量：低质量"),
    ("高质量", "quality", "质量：高质量"),
    ("网络下载", "source", "来源：网络下载"),
    ("手动整理", "source", "来源：手动整理"),
    ("旧版", "source", "来源：旧版"),
    ("新版候选", "source", "来源：新版候选"),
]


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    column = definition.split()[0]
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def migrate_tag_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            category TEXT,
            description TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS book_tags (
            id INTEGER PRIMARY KEY,
            book_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            source TEXT,
            confidence REAL,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    _add_column(conn, "tags", "category TEXT")
    _add_column(conn, "tags", "description TEXT")
    _add_column(conn, "tags", "updated_at TEXT")
    _add_column(conn, "book_tags", "source TEXT")
    _add_column(conn, "book_tags", "confidence REAL")
    _add_column(conn, "book_tags", "created_at TEXT")
    _add_column(conn, "book_tags", "updated_at TEXT")
    if "reading_status" not in _columns(conn, "books"):
        conn.execute("ALTER TABLE books ADD COLUMN reading_status TEXT")
    now = now_ts()
    conn.execute("UPDATE tags SET category = COALESCE(category, 'custom'), updated_at = COALESCE(updated_at, ?) WHERE category IS NULL OR updated_at IS NULL", (now,))
    conn.execute("UPDATE book_tags SET source = COALESCE(source, 'manual'), confidence = COALESCE(confidence, 1.0), created_at = COALESCE(created_at, ?), updated_at = COALESCE(updated_at, ?) WHERE source IS NULL OR confidence IS NULL OR created_at IS NULL OR updated_at IS NULL", (now, now))
    duplicate_names = conn.execute("SELECT name, MIN(id) AS keep_id FROM tags WHERE name IS NOT NULL GROUP BY name HAVING COUNT(*) > 1").fetchall()
    for duplicate in duplicate_names:
        ids = [row["id"] for row in conn.execute("SELECT id FROM tags WHERE name = ? AND id <> ?", (duplicate["name"], duplicate["keep_id"])).fetchall()]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"UPDATE book_tags SET tag_id = ? WHERE tag_id IN ({placeholders})", [duplicate["keep_id"], *ids])
            conn.execute(f"DELETE FROM tags WHERE id IN ({placeholders})", ids)
    conn.execute("DELETE FROM book_tags WHERE id NOT IN (SELECT MIN(id) FROM book_tags GROUP BY book_id, tag_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_name_unique ON tags(name)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_book_tags_book_tag_unique ON book_tags(book_id, tag_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tags_category ON tags(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_book_tags_book_id ON book_tags(book_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_book_tags_tag_id ON book_tags(tag_id)")
    conn.commit()


def initialize_default_tags(conn: sqlite3.Connection) -> int:
    migrate_tag_schema(conn)
    now = now_ts()
    created = 0
    for name, category, description in DEFAULT_TAGS:
        cur = conn.execute(
            "INSERT OR IGNORE INTO tags (name, category, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (name, category, description, now, now),
        )
        created += cur.rowcount
    conn.commit()
    return created


def _tag_by_name(conn: sqlite3.Connection, tag: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM tags WHERE name = ?", (tag,)).fetchone()
    return dict(row) if row else None


def _book_exists(conn: sqlite3.Connection, book_id: int) -> bool:
    return conn.execute("SELECT 1 FROM books WHERE id = ?", (book_id,)).fetchone() is not None


def _log(conn: sqlite3.Connection, repo, operation_type: str, book_id: int | None, reason: str) -> None:
    log_operation(
        conn,
        repo,
        operation_type=operation_type,
        book_id=book_id,
        source_path="",
        target_path="",
        raw_sha256_before=None,
        raw_sha256_after=None,
        status="success",
        report_path=None,
        reason=reason,
    )


def list_tags(conn: sqlite3.Connection, *, category: str = "all", query: str | None = None) -> list[dict[str, Any]]:
    migrate_tag_schema(conn)
    clauses = ["1 = 1"]
    params: list[Any] = []
    if category != "all":
        clauses.append("t.category = ?")
        params.append(category)
    if query:
        like = f"%{query}%"
        clauses.append("(t.name LIKE ? OR COALESCE(t.description, '') LIKE ?)")
        params.extend([like, like])
    where = " AND ".join(f"({clause})" for clause in clauses)
    rows = conn.execute(
        f"""
        SELECT t.id AS tag_id, t.name, t.category, t.description, t.created_at,
               COUNT(bt.book_id) AS book_count
        FROM tags t
        LEFT JOIN book_tags bt ON bt.tag_id = t.id
        WHERE {where}
        GROUP BY t.id
        ORDER BY t.category, t.name
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def create_tag(conn: sqlite3.Connection, repo, *, name: str, category: str = "custom", description: str | None = None) -> dict[str, Any]:
    migrate_tag_schema(conn)
    if category not in VALID_TAG_CATEGORIES:
        category = "custom"
    existing = _tag_by_name(conn, name)
    if existing:
        return {"status": "exists", "tag": existing}
    now = now_ts()
    conn.execute(
        "INSERT INTO tags (name, category, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (name, category, description, now, now),
    )
    tag = _tag_by_name(conn, name)
    _log(conn, repo, "create_tag", None, f"create tag {name} category={category}")
    return {"status": "created", "tag": tag}


def delete_tag(conn: sqlite3.Connection, repo, *, tag: str, dry_run: bool = False, confirm: bool = False) -> dict[str, Any]:
    migrate_tag_schema(conn)
    if dry_run and confirm:
        raise ValueError("--dry-run and --confirm cannot be used together")
    if not dry_run and not confirm:
        raise ValueError("use --dry-run or --confirm")
    row = _tag_by_name(conn, tag)
    if not row:
        return {"status": "not_found", "tag": tag, "book_count": 0}
    count = int(conn.execute("SELECT COUNT(*) FROM book_tags WHERE tag_id = ?", (row["id"],)).fetchone()[0])
    if dry_run:
        return {"status": "dry_run", "tag": tag, "tag_id": row["id"], "book_count": count}
    conn.execute("DELETE FROM book_tags WHERE tag_id = ?", (row["id"],))
    conn.execute("DELETE FROM tags WHERE id = ?", (row["id"],))
    _log(conn, repo, "delete_tag", None, f"delete tag {tag}; affected_books={count}")
    return {"status": "deleted", "tag": tag, "tag_id": row["id"], "book_count": count}


def tag_book(
    conn: sqlite3.Connection,
    repo,
    *,
    book_id: int,
    tag: str,
    source: str = "manual",
    create: bool = False,
    category: str = "custom",
    confidence: float = 1.0,
) -> dict[str, Any]:
    migrate_tag_schema(conn)
    if not _book_exists(conn, book_id):
        return {"status": "book_not_found", "book_id": book_id}
    row = _tag_by_name(conn, tag)
    if not row:
        if not create:
            return {"status": "tag_not_found", "tag": tag}
        row = create_tag(conn, repo, name=tag, category=category).get("tag")
    existing = conn.execute("SELECT * FROM book_tags WHERE book_id = ? AND tag_id = ?", (book_id, row["id"])).fetchone()
    if existing:
        return {"status": "exists", "book_id": book_id, "tag": tag}
    now = now_ts()
    conn.execute(
        "INSERT INTO book_tags (book_id, tag_id, source, confidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (book_id, row["id"], source, confidence, now, now),
    )
    _log(conn, repo, "tag_book" if source == "manual" else "auto_tag", book_id, f"add tag {tag}; source={source}; confidence={confidence}")
    return {"status": "tagged", "book_id": book_id, "tag": tag}


def untag_book(conn: sqlite3.Connection, repo, *, book_id: int, tag: str) -> dict[str, Any]:
    migrate_tag_schema(conn)
    row = _tag_by_name(conn, tag)
    if not row:
        return {"status": "tag_not_found", "tag": tag}
    cur = conn.execute("DELETE FROM book_tags WHERE book_id = ? AND tag_id = ?", (book_id, row["id"]))
    if cur.rowcount == 0:
        return {"status": "relation_not_found", "book_id": book_id, "tag": tag}
    _log(conn, repo, "untag_book", book_id, f"remove tag {tag}")
    return {"status": "untagged", "book_id": book_id, "tag": tag}


def tags_for_books(conn: sqlite3.Connection, book_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    migrate_tag_schema(conn)
    if not book_ids:
        return {}
    placeholders = ",".join("?" for _ in book_ids)
    rows = conn.execute(
        f"""
        SELECT bt.book_id, t.id AS tag_id, t.name, t.category, bt.source, bt.confidence
        FROM book_tags bt
        JOIN tags t ON t.id = bt.tag_id
        WHERE bt.book_id IN ({placeholders})
        ORDER BY t.category, t.name
        """,
        book_ids,
    ).fetchall()
    result: dict[int, list[dict[str, Any]]] = {book_id: [] for book_id in book_ids}
    for row in rows:
        result.setdefault(int(row["book_id"]), []).append(dict(row))
    return result


def books_by_tag(conn: sqlite3.Connection, *, tag: str, area: str = "all", limit: int = 50, sort: str = "updated_at", descending: bool = True) -> list[dict[str, Any]]:
    migrate_tag_schema(conn)
    sort_map = {"quality": "b.quality_score", "file_name": "b.file_name", "updated_at": "b.updated_at"}
    clauses = ["t.name = ?"]
    params: list[Any] = [tag]
    if area != "all":
        clauses.append("b.repo_area = ?")
        params.append(area)
    direction = "DESC" if descending else "ASC"
    rows = conn.execute(
        f"""
        SELECT b.id, b.file_name, b.title_raw, b.title_norm, b.author_raw, b.author_norm,
               b.repo_area, b.quality_score, b.chapter_count, b.current_path, b.updated_at
        FROM books b
        JOIN book_tags bt ON bt.book_id = b.id
        JOIN tags t ON t.id = bt.tag_id
        WHERE {" AND ".join(clauses)}
        ORDER BY {sort_map.get(sort, "b.updated_at")} {direction}, b.id {direction}
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    return [dict(row) for row in rows]


def set_reading_status(conn: sqlite3.Connection, repo, *, book_id: int, status: str, allow_custom_status: bool = False) -> dict[str, Any]:
    migrate_tag_schema(conn)
    if not allow_custom_status and status not in VALID_READING_STATUSES:
        return {"status": "invalid_status", "reading_status": status}
    if not _book_exists(conn, book_id):
        return {"status": "book_not_found", "book_id": book_id}
    conn.execute("UPDATE books SET reading_status = ?, updated_at = ? WHERE id = ?", (status, now_ts(), book_id))
    _log(conn, repo, "set_reading_status", book_id, f"set reading_status={status}")
    return {"status": "updated", "book_id": book_id, "reading_status": status}


def books_by_status(conn: sqlite3.Connection, *, status: str, area: str = "all", limit: int = 50, sort: str = "updated_at", descending: bool = True) -> list[dict[str, Any]]:
    sort_map = {"quality": "quality_score", "file_name": "file_name", "updated_at": "updated_at"}
    clauses = ["reading_status = ?"]
    params: list[Any] = [status]
    if area != "all":
        clauses.append("repo_area = ?")
        params.append(area)
    direction = "DESC" if descending else "ASC"
    rows = conn.execute(
        f"""
        SELECT id, file_name, title_raw, title_norm, author_raw, author_norm,
               repo_area, quality_score, chapter_count, current_path, updated_at, reading_status
        FROM books
        WHERE {" AND ".join(clauses)}
        ORDER BY {sort_map.get(sort, "updated_at")} {direction}, id {direction}
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    return [dict(row) for row in rows]


def auto_tag(conn: sqlite3.Connection, repo, *, dry_run: bool = True, apply: bool = False) -> dict[str, Any]:
    migrate_tag_schema(conn)
    if dry_run and apply:
        dry_run = False
    if not dry_run and not apply:
        dry_run = True
    initialize_default_tags(conn)
    books = conn.execute("SELECT * FROM books ORDER BY id").fetchall()
    suggestions: list[dict[str, Any]] = []
    for row in books:
        book = dict(row)
        text = f"{book.get('file_name') or ''} {book.get('title_raw') or ''}"
        rules: list[tuple[str, float, str]] = []
        if any(key in text for key in ["精校", "校对"]):
            rules.append(("精校", 0.9, "file/title contains 精校 or 校对"))
        has_unfinished = "未完结" in text
        if not has_unfinished and any(key in text for key in ["完本", "全本", "完结"]):
            rules.append(("完本", 0.9, "file/title contains 完本/全本/完结"))
        if "连载" in text:
            rules.append(("连载", 0.85, "file/title contains 连载"))
        if has_unfinished:
            rules.append(("未完结", 0.9, "file/title contains 未完结"))
        if int(book.get("ad_line_count") or 0) > 0:
            rules.append(("待整理", 0.7, "ad_line_count > 0"))
        if int(book.get("ad_line_count") or 0) >= 50 or float(book.get("ad_line_rate") or 0) >= 0.02:
            rules.append(("广告较多", 0.9, "ad_line_count/ad_line_rate high"))
        if float(book.get("mojibake_rate") or 0) >= 0.005:
            rules.append(("疑似乱码", 0.9, "mojibake_rate >= 0.005"))
        if int(book.get("missing_chapter_count") or 0) > 0:
            rules.append(("疑似缺章", 0.9, "missing_chapter_count > 0"))
        if int(book.get("chapter_order_error_count") or 0) > 0 or int(book.get("duplicate_chapter_count") or 0) > 0:
            rules.append(("章节异常", 0.85, "chapter order or duplicate chapter issue"))
        if float(book.get("quality_score") or 0) < 60:
            rules.append(("低质量", 0.85, "quality_score < 60"))
        if float(book.get("quality_score") or 0) >= 90:
            rules.append(("高质量", 0.8, "quality_score >= 90"))
        for tag, confidence, reason in rules:
            tag_row = _tag_by_name(conn, tag)
            exists = bool(tag_row and conn.execute("SELECT 1 FROM book_tags WHERE book_id = ? AND tag_id = ?", (book["id"], tag_row["id"])).fetchone())
            if not exists:
                suggestions.append({"book_id": book["id"], "file_name": book.get("file_name"), "tag": tag, "confidence": confidence, "reason": reason})
    applied = 0
    if apply:
        for item in suggestions:
            result = tag_book(conn, repo, book_id=int(item["book_id"]), tag=item["tag"], source="auto", create=False, confidence=float(item["confidence"]))
            if result["status"] == "tagged":
                applied += 1
    return {"dry_run": dry_run, "applied": applied, "suggestions": suggestions}


def tag_status_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    migrate_tag_schema(conn)
    total_books = int(conn.execute("SELECT COUNT(*) FROM books").fetchone()[0])
    tag_total = int(conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0])
    tagged_books = int(conn.execute("SELECT COUNT(DISTINCT book_id) FROM book_tags").fetchone()[0])
    category_rows = conn.execute("SELECT COALESCE(category, 'custom') AS category, COUNT(*) AS count FROM tags GROUP BY COALESCE(category, 'custom')").fetchall()
    top_tags = conn.execute(
        """
        SELECT t.name, t.category, COUNT(bt.book_id) AS book_count
        FROM tags t LEFT JOIN book_tags bt ON bt.tag_id = t.id
        GROUP BY t.id ORDER BY book_count DESC, t.name ASC LIMIT 20
        """
    ).fetchall()
    status_rows = conn.execute("SELECT COALESCE(reading_status, '') AS status, COUNT(*) AS count FROM books GROUP BY COALESCE(reading_status, '')").fetchall()
    source_rows = conn.execute("SELECT COALESCE(source, 'manual') AS source, COUNT(*) AS count FROM book_tags GROUP BY COALESCE(source, 'manual')").fetchall()
    return {
        "tag_total": tag_total,
        "tagged_books": tagged_books,
        "untagged_books": max(0, total_books - tagged_books),
        "category_counts": {row["category"]: row["count"] for row in category_rows},
        "top_tags": [dict(row) for row in top_tags],
        "reading_status_counts": {("未设置" if row["status"] == "" else row["status"]): row["count"] for row in status_rows},
        "unset_reading_status": int(conn.execute("SELECT COUNT(*) FROM books WHERE reading_status IS NULL OR reading_status = ''").fetchone()[0]),
        "source_counts": Counter({row["source"]: row["count"] for row in source_rows}),
    }
