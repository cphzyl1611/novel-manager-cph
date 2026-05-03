from __future__ import annotations

import json
import sqlite3
from typing import Any

from .tag_manager import tags_for_books


BOOK_SORT_COLUMNS = {
    "quality": "quality_score",
    "file_name": "file_name",
    "chapter_count": "chapter_count",
    "char_count": "char_count_clean",
    "ad_line_count": "ad_line_count",
    "mojibake_rate": "mojibake_rate",
    "updated_at": "updated_at",
}


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _query_clause(query: str | None, params: list[Any]) -> str:
    if not query:
        return ""
    like = f"%{query}%"
    params.extend([like, like, like, like, like, like])
    return """
        AND (
            file_name LIKE ? OR title_raw LIKE ? OR title_norm LIKE ?
            OR author_raw LIKE ? OR author_norm LIKE ? OR current_path LIKE ?
        )
    """


def list_books(
    conn: sqlite3.Connection,
    *,
    area: str = "all",
    limit: int = 50,
    sort: str = "updated_at",
    descending: bool = True,
    min_quality: float = 0,
    max_quality: float = 100,
    query: str | None = None,
    poor_only: bool = False,
    problem_only: bool = False,
    tag: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    clauses = ["1 = 1"]
    if area != "all":
        clauses.append("repo_area = ?")
        params.append(area)
    clauses.append("COALESCE(quality_score, 0) >= ?")
    params.append(min_quality)
    clauses.append("COALESCE(quality_score, 0) <= ?")
    params.append(max_quality)
    query_sql = _query_clause(query, params)
    if query_sql:
        clauses.append(query_sql.replace("AND", "", 1))
    if poor_only:
        clauses.append("(quality_level = 'poor' OR COALESCE(quality_score, 0) < 60)")
    if problem_only:
        clauses.append(
            """
            (
                COALESCE(ad_line_count, 0) > 0 OR COALESCE(mojibake_rate, 0) > 0
                OR COALESCE(duplicate_chapter_count, 0) > 0
                OR COALESCE(missing_chapter_count, 0) > 0
                OR COALESCE(chapter_order_error_count, 0) > 0
                OR COALESCE(truncated_risk, 0) = 1
            )
            """
        )
    if status:
        clauses.append("reading_status = ?")
        params.append(status)
    if tag:
        clauses.append("EXISTS (SELECT 1 FROM book_tags bt JOIN tags t ON t.id = bt.tag_id WHERE bt.book_id = books.id AND t.name = ?)")
        params.append(tag)
    where = " AND ".join(f"({clause})" for clause in clauses)
    total_books = int(conn.execute("SELECT COUNT(*) FROM books").fetchone()[0])
    total = int(conn.execute(f"SELECT COUNT(*) FROM books WHERE {where}", params).fetchone()[0])
    sort_column = BOOK_SORT_COLUMNS.get(sort, "updated_at")
    direction = "DESC" if descending else "ASC"
    rows = conn.execute(
        f"""
        SELECT id, repo_area, file_name, title_raw, title_norm, author_raw, author_norm,
               quality_score, quality_level, chapter_count, char_count_clean, ad_line_count,
               mojibake_rate, reading_status, current_path, updated_at
        FROM books
        WHERE {where}
        ORDER BY {sort_column} {direction}, id {direction}
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    result_rows = [dict(row) for row in rows]
    tag_map = tags_for_books(conn, [int(row["id"]) for row in result_rows])
    for row in result_rows:
        row["tags"] = tag_map.get(int(row["id"]), [])
        row["tag_names"] = [item["name"] for item in row["tags"]]
    return {"rows": result_rows, "shown": len(rows), "total": total, "total_books": total_books}


def find_book_by_id(conn: sqlite3.Connection, book_id: int) -> dict[str, Any] | None:
    return _row_dict(conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone())


def find_book_by_path(conn: sqlite3.Connection, path: str) -> dict[str, Any] | None:
    return _row_dict(conn.execute("SELECT * FROM books WHERE current_path = ?", (path,)).fetchone())


def search_book_candidates(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[dict[str, Any]]:
    result = list_books(conn, query=query, limit=limit, sort="updated_at", descending=True)
    return result["rows"]


def get_chapters(conn: sqlite3.Connection, book_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT chapter_index, chapter_no, chapter_type, title_raw, char_count, order_status
        FROM chapters
        WHERE book_id = ?
        ORDER BY chapter_index ASC
        """,
        (book_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def preview_chapters(chapters: list[dict[str, Any]], *, show_all: bool = False, chapter_limit: int = 30) -> list[dict[str, Any]]:
    if show_all or len(chapters) <= chapter_limit:
        return chapters
    if chapter_limit <= 0:
        return []
    if chapter_limit <= 15:
        return chapters[:chapter_limit]
    head_count = min(10, chapter_limit)
    tail_count = min(5, max(0, chapter_limit - head_count))
    middle_count = max(0, chapter_limit - head_count - tail_count)
    return chapters[: head_count + middle_count] + chapters[-tail_count:] if tail_count else chapters[:chapter_limit]


def parse_quality_reasons(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [raw]
    if isinstance(data, list):
        return [str(item) for item in data]
    return [str(data)]


def inspect_book(
    conn: sqlite3.Connection,
    *,
    book_id: int | None = None,
    path: str | None = None,
    query: str | None = None,
    show_all_chapters: bool = False,
    chapter_limit: int = 30,
) -> dict[str, Any]:
    total_books = int(conn.execute("SELECT COUNT(*) FROM books").fetchone()[0])
    if total_books == 0:
        return {"status": "empty", "message": "数据库还没有扫描数据，请先运行 scan。"}
    if query and book_id is None and path is None:
        candidates = search_book_candidates(conn, query)
        return {"status": "candidates", "candidates": candidates, "message": "请从候选结果中指定 book_id。"}
    book = find_book_by_id(conn, book_id) if book_id is not None else None
    if book is None and path:
        book = find_book_by_path(conn, path)
    if book is None:
        return {"status": "not_found", "message": "没有找到匹配的小说。"}
    chapters = get_chapters(conn, int(book["id"]))
    tags = tags_for_books(conn, [int(book["id"])]).get(int(book["id"]), [])
    return {
        "status": "ok",
        "book": book,
        "tags": tags,
        "chapters": preview_chapters(chapters, show_all=show_all_chapters, chapter_limit=chapter_limit),
        "chapter_total": len(chapters),
        "quality_reasons": parse_quality_reasons(book.get("quality_reasons_json")),
    }
