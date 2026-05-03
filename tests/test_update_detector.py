import json
import sqlite3
import uuid
from pathlib import Path

from novel_manager.db import initialize, replace_chapters, upsert_book
from novel_manager.summary_report import generate_summary_report
from novel_manager.update_detector import (
    compare_update_pair,
    compute_coverage_score,
    compute_new_content_score,
    find_update_candidates,
    generate_update_report,
    save_update_candidates,
)


def memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize(conn)
    return conn


def repo():
    root = Path(".tmp") / "update_tests" / uuid.uuid4().hex
    (root / "reports" / "update").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "summary").mkdir(parents=True, exist_ok=True)
    return root


def book(path, area, title="书名", author="作者", chapters=3, chars=3000, score=90, ads=0, mojibake=0.0):
    return {
        "current_path": path,
        "original_path": path,
        "repo_area": area,
        "file_name": Path(path).name,
        "file_size": chars,
        "mtime": 1.0,
        "raw_sha256": path + "r",
        "clean_sha256": path + "c",
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
        "chapter_count": chapters,
        "mojibake_rate": mojibake,
        "ad_line_count": ads,
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
        "updated_at": "2026-01-02 00:00:00",
    }


def add_chapters(conn, book_id, names):
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


def row(conn, book_id):
    return dict(conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone())


def test_same_work_score_high_and_author_conflict_low_title():
    with memory_conn() as conn:
        old = upsert_book(conn, book("old.txt", "library"))
        new = upsert_book(conn, book("new.txt", "incoming", chapters=4, chars=4000))
        add_chapters(conn, old, ["第1章", "第2章", "第3章"])
        add_chapters(conn, new, ["第1章", "第2章", "第3章", "第4章"])
        candidate = compare_update_pair(conn, row(conn, old), row(conn, new), text_lookup=lambda _: "正文" * 1000)
        conflict = compare_update_pair(conn, row(conn, old), {**row(conn, new), "author_norm": "别人"}, text_lookup=lambda _: "正文" * 1000)
        different = compare_update_pair(conn, {**row(conn, old), "title_norm": "甲"}, {**row(conn, new), "title_norm": "乙"}, text_lookup=lambda _: "不同" * 10)
    assert candidate["same_work_score"] > 0.85
    assert "author_conflict" in conflict["risk_flags"]
    assert different["same_work_score"] < candidate["same_work_score"]


def test_coverage_score_high_and_low():
    old = [{"title_norm": "1"}, {"title_norm": "2"}, {"title_norm": "3"}]
    new = [{"title_norm": "1"}, {"title_norm": "2"}, {"title_norm": "3"}, {"title_norm": "4"}]
    low = [{"title_norm": "1"}]
    assert compute_coverage_score(old, new)["coverage_score"] == 1.0
    assert compute_coverage_score(old, low)["coverage_score"] < 0.5


def test_new_content_score_variants():
    old = book("old", "library", chapters=10, chars=10000)
    newer = book("new", "incoming", chapters=15, chars=15000)
    chars_only = book("new2", "incoming", chapters=10, chars=15000)
    same = book("same", "incoming", chapters=10, chars=10000)
    assert compute_new_content_score(old, newer, [], [])["new_content_score"] > 0.5
    assert compute_new_content_score(old, chars_only, [], [])["new_content_score"] > 0
    assert compute_new_content_score(old, same, [], [])["new_content_score"] == 0


def test_recommendations_replace_manual_reject():
    with memory_conn() as conn:
        old = upsert_book(conn, book("old.txt", "library", chapters=3, chars=3000, score=90))
        new = upsert_book(conn, book("new.txt", "incoming", chapters=5, chars=5000, score=90))
        bad = upsert_book(conn, book("bad.txt", "incoming", author="别人", chapters=1, chars=500, score=40, ads=100))
        add_chapters(conn, old, ["第1章", "第2章", "第3章"])
        add_chapters(conn, new, ["第1章", "第2章", "第3章", "第4章", "第5章"])
        add_chapters(conn, bad, ["别的"])
        good_candidate = compare_update_pair(conn, row(conn, old), row(conn, new), text_lookup=lambda _: "正文" * 1000)
        reject = compare_update_pair(conn, row(conn, old), row(conn, bad), text_lookup=lambda _: "不同" * 100)
    assert good_candidate["recommendation"] == "replace_recommended"
    assert reject["recommendation"] == "reject"


def test_check_updates_report_and_save_candidates():
    root = repo()
    with memory_conn() as conn:
        old = upsert_book(conn, book("old.txt", "library", title="高考陪读"))
        new = upsert_book(conn, book("new.txt", "incoming", title="高考陪读", chapters=4, chars=4000))
        other = upsert_book(conn, book("other.txt", "library", title="其他"))
        add_chapters(conn, old, ["第1章", "第2章", "第3章"])
        add_chapters(conn, new, ["第1章", "第2章", "第3章", "第4章"])
        add_chapters(conn, other, ["第1章"])
        result = find_update_candidates(conn, query="高考", include_rejected=True, text_lookup=lambda _: "正文" * 1000)
        assert result["candidates"]
        assert all(c["new_book_id"] == new for c in result["candidates"])
        assert conn.execute("SELECT COUNT(*) FROM update_candidates").fetchone()[0] == 0
        saved = save_update_candidates(conn, result["candidates"])
        assert saved == len(result["candidates"])
        html, js, md = generate_update_report(root, result, saved)
    assert html.exists() and js.exists() and md.exists()
    data = json.loads(js.read_text(encoding="utf-8"))
    assert "recommendation" in data["candidates"][0]
    assert "risk_flags" in data["candidates"][0]
    assert "reason_summary" in data["candidates"][0]
    assert "本报告不执行替换" in html.read_text(encoding="utf-8")


def test_include_rejected_and_dry_run():
    with memory_conn() as conn:
        old = upsert_book(conn, book("old.txt", "library", title="同书"))
        new = upsert_book(conn, book("new.txt", "incoming", title="同书", author="冲突"))
        add_chapters(conn, old, ["第1章"])
        add_chapters(conn, new, ["别的"])
        hidden = find_update_candidates(conn, include_rejected=False, text_lookup=lambda _: "不同")
        shown = find_update_candidates(conn, include_rejected=True, text_lookup=lambda _: "不同")
        dry = find_update_candidates(conn, dry_run=True)
    assert len(shown["candidates"]) >= len(hidden["candidates"])
    assert dry["pairs_to_check"] >= 1
    assert dry["candidates"] == []


def test_summary_report_counts_update_report():
    root = repo()
    payload = {
        "generated_at": "x",
        "incoming_count": 1,
        "library_count": 1,
        "candidates": [
            {"recommendation": "replace_recommended", "risk_flags": []},
            {"recommendation": "manual_review", "risk_flags": ["quality_drop", "ad_line_increase"]},
            {"recommendation": "reject", "risk_flags": ["author_conflict", "mojibake_increase"]},
        ],
    }
    (root / "reports" / "update" / "update_report_x.json").write_text(json.dumps(payload), encoding="utf-8")
    text = generate_summary_report(root).read_text(encoding="utf-8")
    assert "更新检测汇总" in text
    assert "replace_recommended" in text
