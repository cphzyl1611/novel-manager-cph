import json
import sqlite3

from novel_manager.book_viewer import inspect_book, list_books
from novel_manager.db import initialize, replace_chapters, upsert_book


def memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize(conn)
    return conn


def make_book(path, score=80, level="good", ads=0, mojibake=0.0, missing=0, truncated=0):
    return {
        "current_path": path,
        "original_path": path,
        "repo_area": "library",
        "file_name": path.split("/")[-1],
        "file_size": 100,
        "mtime": 1.0,
        "raw_sha256": "a" * 64,
        "clean_sha256": "b" * 64,
        "title_raw": "测试书",
        "title_norm": "测试书",
        "author_raw": "作者",
        "author_norm": "作者",
        "encoding": "utf-8",
        "encoding_confidence": 1.0,
        "decode_status": "ok",
        "char_count_raw": 1000,
        "char_count_clean": 900,
        "line_count_raw": 100,
        "line_count_clean": 90,
        "chapter_count": 2,
        "mojibake_rate": mojibake,
        "ad_line_count": ads,
        "ad_line_rate": 0.1 if ads else 0.0,
        "duplicate_chapter_count": 0,
        "missing_chapter_count": missing,
        "chapter_order_error_count": 0,
        "truncated_risk": truncated,
        "quality_score": score,
        "quality_level": level,
        "quality_reasons_json": json.dumps(["原因一", "原因二"], ensure_ascii=False),
        "status": "active",
        "reading_status": None,
        "created_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-02 00:00:00",
    }


def test_list_books_empty_database_does_not_crash():
    with memory_conn() as conn:
        result = list_books(conn)
    assert result["rows"] == []
    assert result["total_books"] == 0


def test_list_books_returns_rows_and_query_filter():
    with memory_conn() as conn:
        upsert_book(conn, make_book("D:/repo/library/A.txt"))
        upsert_book(conn, make_book("D:/repo/library/B.txt"))
        result = list_books(conn, query="A.txt")
    assert result["total"] == 1
    assert result["rows"][0]["file_name"] == "A.txt"


def test_list_books_poor_only_and_problem_only():
    with memory_conn() as conn:
        upsert_book(conn, make_book("D:/repo/library/good.txt", score=90, level="excellent"))
        upsert_book(conn, make_book("D:/repo/library/poor.txt", score=40, level="poor"))
        upsert_book(conn, make_book("D:/repo/library/problem.txt", score=80, level="good", ads=2))
        poor = list_books(conn, poor_only=True)
        problem = list_books(conn, problem_only=True)
    assert [row["file_name"] for row in poor["rows"]] == ["poor.txt"]
    assert [row["file_name"] for row in problem["rows"]] == ["problem.txt"]


def test_inspect_book_existing_with_chapters_and_reasons():
    with memory_conn() as conn:
        book_id = upsert_book(conn, make_book("D:/repo/library/A.txt"))
        replace_chapters(
            conn,
            book_id,
            [
                {
                    "chapter_index": 1,
                    "chapter_no": 1,
                    "chapter_type": "chapter",
                    "title_raw": "第1章",
                    "title_norm": "第1章",
                    "start_offset": 0,
                    "end_offset": 10,
                    "char_count": 10,
                    "body_clean_sha256": "c" * 64,
                    "is_duplicate_suspect": 0,
                    "is_missing_suspect": 0,
                    "order_status": "ok",
                }
            ],
        )
        result = inspect_book(conn, book_id=book_id)
    assert result["status"] == "ok"
    assert result["book"]["id"] == book_id
    assert result["chapters"][0]["title_raw"] == "第1章"
    assert result["quality_reasons"] == ["原因一", "原因二"]


def test_inspect_book_not_found_is_friendly():
    with memory_conn() as conn:
        upsert_book(conn, make_book("D:/repo/library/A.txt"))
        result = inspect_book(conn, book_id=999)
    assert result["status"] == "not_found"
    assert "没有找到" in result["message"]
