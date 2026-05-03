import sqlite3
import uuid
from pathlib import Path

from novel_manager.db import initialize, upsert_book
from novel_manager.summary_report import generate_summary_report
from novel_manager.work_groups import (
    apply_group_candidates,
    generate_group_candidates,
    group_books,
    inspect_group,
    list_groups,
    merge_groups,
    migrate_work_group_schema,
    set_primary,
    split_group,
)


def memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize(conn)
    migrate_work_group_schema(conn)
    return conn


def make_repo():
    repo = Path(".tmp") / "work_group_tests" / uuid.uuid4().hex
    (repo / "reports" / "group").mkdir(parents=True, exist_ok=True)
    (repo / "reports" / "summary").mkdir(parents=True, exist_ok=True)
    return repo


def book(path, title="书A", author="作者A", raw="raw1", clean="clean1", score=80, area="library", chapters=10, chars=10000, ads=0, mojibake=0.0):
    return {
        "current_path": path,
        "original_path": path,
        "repo_area": area,
        "file_name": path.split("/")[-1],
        "file_size": 100,
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
        "line_count_raw": 100,
        "line_count_clean": 90,
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


def test_clean_and_raw_hash_generate_candidates():
    with memory_conn() as conn:
        upsert_book(conn, book("A.txt", raw="r1", clean="same"))
        upsert_book(conn, book("A2.txt", raw="r2", clean="same"))
        upsert_book(conn, book("B.txt", title="书B", raw="rawsame", clean="c1"))
        upsert_book(conn, book("B2.txt", title="书B", raw="rawsame", clean="c2"))
        candidates = generate_group_candidates(conn)
    sources = {item["group_source"] for item in candidates}
    assert "clean_sha256" in sources
    assert "raw_sha256" in sources


def test_title_author_same_and_author_conflict_manual_review():
    with memory_conn() as conn:
        upsert_book(conn, book("A.txt", title="同书", author="甲", raw="1", clean="1"))
        upsert_book(conn, book("A2.txt", title="同书", author="甲", raw="2", clean="2"))
        upsert_book(conn, book("C.txt", title="冲突", author="甲", raw="3", clean="3"))
        upsert_book(conn, book("C2.txt", title="冲突", author="乙", raw="4", clean="4"))
        candidates = generate_group_candidates(conn, include_low_confidence=True)
    exact = [item for item in candidates if item["group_source"] == "title_author_exact"]
    conflict = [item for item in candidates if item["group_source"] == "title_author_conflict"]
    assert exact
    assert conflict
    assert conflict[0]["manual_review"] is True
    assert conflict[0]["auto_apply"] is False


def test_low_confidence_missing_author_marked_manual_review():
    with memory_conn() as conn:
        upsert_book(conn, book("A.txt", title="缺作者", author="", raw="1", clean="1"))
        upsert_book(conn, book("A2.txt", title="缺作者", author="甲", raw="2", clean="2"))
        candidates = generate_group_candidates(conn, include_low_confidence=True)
    candidate = [item for item in candidates if item["group_source"] == "title_missing_author"][0]
    assert candidate["manual_review"] is True


def test_primary_selection_priorities():
    with memory_conn() as conn:
        incoming_high = upsert_book(conn, book("incoming.txt", raw="1", clean="same", score=99, area="incoming", chapters=20))
        library_lower = upsert_book(conn, book("library.txt", raw="2", clean="same", score=80, area="library", chapters=10))
        candidates = generate_group_candidates(conn)
    assert candidates[0]["recommended_primary_book_id"] == library_lower
    assert candidates[0]["recommended_primary_book_id"] != incoming_high


def test_primary_selection_quality_chapters_and_ads():
    with memory_conn() as conn:
        high = upsert_book(conn, book("high.txt", raw="1", clean="same", score=90, chapters=20, ads=0))
        upsert_book(conn, book("low.txt", raw="2", clean="same", score=70, chapters=25, ads=0))
        candidates = generate_group_candidates(conn)
    assert candidates[0]["recommended_primary_book_id"] == high


def test_group_books_default_and_dry_run_do_not_write_apply_writes():
    repo = make_repo()
    with memory_conn() as conn:
        upsert_book(conn, book("A.txt", raw="1", clean="same"))
        upsert_book(conn, book("A2.txt", raw="2", clean="same"))
        result = group_books(conn, repo)
        assert result["candidates"]
        assert conn.execute("SELECT COUNT(*) FROM work_groups").fetchone()[0] == 0
        group_books(conn, repo, dry_run=True)
        assert conn.execute("SELECT COUNT(*) FROM work_groups").fetchone()[0] == 0
        group_books(conn, repo, apply=True, min_confidence=0.95)
        assert conn.execute("SELECT COUNT(*) FROM work_groups").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM book_group_members").fetchone()[0] == 2


def test_min_confidence_blocks_apply():
    repo = make_repo()
    with memory_conn() as conn:
        upsert_book(conn, book("A.txt", title="同书", author="甲", raw="1", clean="1"))
        upsert_book(conn, book("A2.txt", title="同书", author="甲", raw="2", clean="2"))
        group_books(conn, repo, apply=True, min_confidence=0.99)
        assert conn.execute("SELECT COUNT(*) FROM work_groups").fetchone()[0] == 0


def test_list_and_inspect_groups():
    repo = make_repo()
    with memory_conn() as conn:
        upsert_book(conn, book("A.txt", title="查询书", raw="1", clean="same"))
        upsert_book(conn, book("A2.txt", title="查询书", raw="2", clean="same"))
        group_books(conn, repo, apply=True)
        groups = list_groups(conn, query="查询")
        detail = inspect_group(conn, groups[0]["group_id"])
        missing = inspect_group(conn, 999)
    assert len(groups) == 1
    assert detail["status"] == "ok"
    assert len(detail["members"]) == 2
    assert missing["status"] == "not_found"


def test_set_primary_accepts_member_rejects_non_member():
    repo = make_repo()
    with memory_conn() as conn:
        first = upsert_book(conn, book("A.txt", raw="1", clean="same"))
        second = upsert_book(conn, book("A2.txt", raw="2", clean="same"))
        outsider = upsert_book(conn, book("B.txt", title="B", raw="3", clean="3"))
        group_books(conn, repo, apply=True)
        group_id = list_groups(conn)[0]["group_id"]
        ok = set_primary(conn, group_id, second)
        bad = set_primary(conn, group_id, outsider)
        primary = conn.execute("SELECT primary_book_id FROM work_groups WHERE id = ?", (group_id,)).fetchone()[0]
    assert ok["status"] == "ok"
    assert bad["status"] == "error"
    assert primary == second
    assert primary != first


def test_merge_groups_keeps_source_group():
    repo = make_repo()
    with memory_conn() as conn:
        apply_group_candidates(
            conn,
            [
                {
                    "canonical_title": "A",
                    "canonical_author": "甲",
                    "recommended_primary_book_id": upsert_book(conn, book("A.txt", raw="1", clean="1")),
                    "group_confidence": 1.0,
                    "group_source": "test",
                    "group_reason": "test",
                    "manual_review": False,
                    "members": [{"book_id": 1, "role": "primary", "confidence": 1.0, "source": "test", "member_reason": "test"}],
                },
                {
                    "canonical_title": "B",
                    "canonical_author": "甲",
                    "recommended_primary_book_id": upsert_book(conn, book("B.txt", title="B", raw="2", clean="2")),
                    "group_confidence": 1.0,
                    "group_source": "test",
                    "group_reason": "test",
                    "manual_review": False,
                    "members": [{"book_id": 2, "role": "primary", "confidence": 1.0, "source": "test", "member_reason": "test"}],
                },
            ],
        )
        result = merge_groups(conn, 2, 1)
        source = conn.execute("SELECT status FROM work_groups WHERE id = 2").fetchone()[0]
        members = conn.execute("SELECT COUNT(*) FROM book_group_members WHERE work_group_id = 1").fetchone()[0]
    assert result["status"] == "ok"
    assert source == "merged"
    assert members == 2


def test_split_group_moves_book_and_reselects_primary():
    repo = make_repo()
    with memory_conn() as conn:
        first = upsert_book(conn, book("A.txt", raw="1", clean="same", score=90))
        second = upsert_book(conn, book("A2.txt", raw="2", clean="same", score=80))
        group_books(conn, repo, apply=True)
        result = split_group(conn, first)
        old_primary = conn.execute("SELECT primary_book_id FROM work_groups WHERE id = ?", (result["old_group_id"],)).fetchone()[0]
        new_primary = conn.execute("SELECT primary_book_id FROM work_groups WHERE id = ?", (result["new_group_id"],)).fetchone()[0]
    assert result["status"] == "ok"
    assert old_primary == second
    assert new_primary == first


def test_summary_report_includes_group_summary():
    repo = make_repo()
    with memory_conn() as conn:
        upsert_book(conn, book("A.txt", raw="1", clean="same"))
        upsert_book(conn, book("A2.txt", raw="2", clean="same"))
        group_books(conn, repo)
    output = generate_summary_report(repo)
    assert "作品分组汇总" in output.read_text(encoding="utf-8")
