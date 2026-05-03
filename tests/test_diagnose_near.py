import json
import sqlite3
import uuid
from pathlib import Path

from novel_manager.db import initialize, replace_chapters, upsert_book
from novel_manager.diagnose_near import diagnose_near
from novel_manager.near_duplicate import candidate_pairs, find_near_duplicates
from novel_manager.report_index import generate_report_index, list_reports
from novel_manager.summary_report import generate_summary_report
from novel_manager.work_groups import migrate_work_group_schema


def memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize(conn)
    migrate_work_group_schema(conn)
    return conn


def repo():
    root = Path(".tmp") / "diagnose_near_tests" / uuid.uuid4().hex
    (root / "reports" / "diagnostic").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "summary").mkdir(parents=True, exist_ok=True)
    return root


def book(path, title, raw, clean, author="作者", chars=5000):
    return {
        "current_path": path,
        "original_path": path,
        "repo_area": "library",
        "file_name": Path(path).name,
        "file_size": chars,
        "mtime": 1.0,
        "raw_sha256": raw,
        "clean_sha256": clean,
        "title_raw": title,
        "title_norm": title,
        "author_raw": author,
        "author_norm": author,
        "encoding": "utf-8",
        "encoding_confidence": 1.0,
        "decode_status": "ok",
        "char_count_raw": chars,
        "char_count_clean": chars,
        "line_count_raw": 10,
        "line_count_clean": 10,
        "chapter_count": 2,
        "mojibake_rate": 0.0,
        "ad_line_count": 0,
        "ad_line_rate": 0.0,
        "duplicate_chapter_count": 0,
        "missing_chapter_count": 0,
        "chapter_order_error_count": 0,
        "truncated_risk": 0,
        "quality_score": 80,
        "quality_level": "good",
        "quality_reasons_json": "[]",
        "status": "active",
        "reading_status": None,
        "created_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-02 00:00:00",
    }


def chapters(conn, book_id, names=("第1章", "第2章")):
    replace_chapters(
        conn,
        book_id,
        [
            {
                "chapter_index": i,
                "chapter_no": i,
                "chapter_type": "chapter",
                "title_raw": name,
                "title_norm": name,
                "start_offset": 0,
                "end_offset": 1,
                "char_count": 1,
                "body_clean_sha256": "x",
                "is_duplicate_suspect": 0,
                "is_missing_suspect": 0,
                "order_status": "ok",
            }
            for i, name in enumerate(names, 1)
        ],
    )


def seed(conn):
    a = upsert_book(conn, book("高考陪读那三年.txt", "高考陪读那三年", "r1", "c1"))
    b = upsert_book(conn, book("高考陪读那三年 (2).txt", "高考陪读那三年", "r2", "c2"))
    c = upsert_book(conn, book("温暖.txt", "温暖", "r3", "c3"))
    d = upsert_book(conn, book("温暖 (2).txt", "温暖", "r3", "c4"))
    for book_id in (a, b, c, d):
        chapters(conn, book_id)
    return a, b, c, d


def test_diagnose_near_outputs_reports_and_low_score_rows():
    root = repo()
    with memory_conn() as conn:
        seed(conn)
        result = diagnose_near(conn, root, query="高考陪读", text_lookup=lambda _: "完全不同" * 10)
    assert result["json_path"].exists()
    assert result["html_path"].exists()
    assert result["md_path"].exists()
    data = json.loads(result["json_path"].read_text(encoding="utf-8"))
    assert data["pairs"]
    assert "filter_reason" in data["pairs"][0]


def test_diagnose_query_limits_scope():
    root = repo()
    with memory_conn() as conn:
        seed(conn)
        result = diagnose_near(conn, root, query="温暖", text_lookup=lambda _: "正文" * 100)
    assert all("温暖" in row["file_a"] or "温暖" in row["file_b"] for row in result["payload"]["pairs"])


def test_candidate_blocking_same_and_similar_titles_and_exact_skip():
    with memory_conn() as conn:
        seed(conn)
        books = [dict(row) for row in conn.execute("SELECT * FROM books").fetchall()]
        pairs = candidate_pairs(books, min_candidate_title_score=0.70)
        result = diagnose_near(conn, repo(), query="温暖", include_exact=False, text_lookup=lambda _: "正文" * 100)
        exact_rows = [row for row in result["payload"]["pairs"] if row["filter_status"] == "skipped_exact_duplicate"]
        result_include = diagnose_near(conn, repo(), query="温暖", include_exact=True, text_lookup=lambda _: "正文" * 100)
    assert pairs
    assert exact_rows
    assert any(row["filter_status"] != "skipped_exact_duplicate" for row in result_include["payload"]["pairs"])


def test_find_near_low_confidence_expands_recall():
    with memory_conn() as conn:
        seed(conn)
        strict = find_near_duplicates(conn, min_score=0.99, text_lookup=lambda _: "不同" * 10)
        loose = find_near_duplicates(conn, min_score=0.65, include_low_confidence=True, text_lookup=lambda _: "不同" * 10)
    assert len(loose) >= len(strict)


def test_report_index_lists_diagnostic_and_summary_includes_it():
    root = repo()
    with memory_conn() as conn:
        seed(conn)
        diagnose_near(conn, root, query="高考", text_lookup=lambda _: "正文" * 100)
    reports = list_reports(root, report_type="diagnostic")
    html, md = generate_report_index(root)
    summary = generate_summary_report(root).read_text(encoding="utf-8")
    assert reports
    assert "diagnostic" in html.read_text(encoding="utf-8")
    assert "diagnostic" in md.read_text(encoding="utf-8")
    assert "近似重复诊断" in summary
