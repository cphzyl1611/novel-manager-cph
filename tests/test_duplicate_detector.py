import sqlite3

from novel_manager.db import initialize, upsert_book
from novel_manager.duplicate_detector import find_exact_duplicates


def make_book(path, raw, clean, score, area="library", chapters=10):
    return {
        "current_path": path,
        "original_path": path,
        "repo_area": area,
        "file_name": path.split("/")[-1],
        "file_size": 10,
        "mtime": 1.0,
        "raw_sha256": raw,
        "clean_sha256": clean,
        "title_raw": "A",
        "title_norm": "a",
        "author_raw": "B",
        "author_norm": "b",
        "encoding": "utf-8",
        "encoding_confidence": 1.0,
        "decode_status": "ok",
        "char_count_raw": 1000,
        "char_count_clean": 1000,
        "line_count_raw": 10,
        "line_count_clean": 10,
        "chapter_count": chapters,
        "mojibake_rate": 0.0,
        "ad_line_count": 0,
        "ad_line_rate": 0.0,
        "duplicate_chapter_count": 0,
        "missing_chapter_count": 0,
        "chapter_order_error_count": 0,
        "truncated_risk": 0,
        "quality_score": score,
        "quality_level": "good",
        "quality_reasons_json": "[]",
        "status": "active",
        "reading_status": None,
        "created_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-01 00:00:00",
    }


def memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def test_raw_sha256_groups():
    with memory_conn() as conn:
        initialize(conn)
        upsert_book(conn, make_book("a.txt", "raw", "clean1", 60))
        upsert_book(conn, make_book("b.txt", "raw", "clean2", 90))
        groups = find_exact_duplicates(conn, "all")
    assert len(groups) == 1
    assert groups[0]["group_type"] == "raw_exact"


def test_clean_sha256_groups():
    with memory_conn() as conn:
        initialize(conn)
        upsert_book(conn, make_book("a.txt", "raw1", "clean", 60))
        upsert_book(conn, make_book("b.txt", "raw2", "clean", 90))
        groups = find_exact_duplicates(conn, "all")
    assert len(groups) == 1
    assert groups[0]["group_type"] == "clean_exact"


def test_recommends_higher_quality():
    with memory_conn() as conn:
        initialize(conn)
        low = upsert_book(conn, make_book("a.txt", "raw", "clean1", 60))
        high = upsert_book(conn, make_book("b.txt", "raw", "clean2", 90))
        groups = find_exact_duplicates(conn, "all")
    assert groups[0]["recommended_keep_book_id"] == high
    roles = {m["book"]["id"]: m["suggested_role"] for m in groups[0]["members"]}
    assert roles[high] == "keep"
    assert roles[low] == "archive_candidate"
