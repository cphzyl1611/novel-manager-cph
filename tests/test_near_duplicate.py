import json
import sqlite3
import uuid
from pathlib import Path

from novel_manager.db import initialize, replace_chapters, upsert_book
from novel_manager.near_duplicate import (
    apply_near_duplicates,
    apply_near_to_work_groups,
    author_similarity,
    chunk_hashes,
    compare_books,
    find_near_duplicates,
    jaccard_similarity,
    length_reasonableness,
    simhash_similarity,
    text_simhash,
    title_similarity,
)
from novel_manager.cli import main
from novel_manager.reports import generate_duplicate_report
from novel_manager.summary_report import generate_summary_report
from novel_manager.work_groups import migrate_work_group_schema


def conn():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    initialize(db)
    migrate_work_group_schema(db)
    return db


def repo():
    root = Path(".tmp") / "near_tests" / uuid.uuid4().hex
    (root / "reports" / "duplicate").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "summary").mkdir(parents=True, exist_ok=True)
    return root


def make_book(path, title="书名", author="作者", raw="r1", clean="c1", chars=10000, chapters=3, score=90):
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
        "line_count_raw": 100,
        "line_count_clean": 90,
        "chapter_count": chapters,
        "mojibake_rate": 0.0,
        "ad_line_count": 0,
        "ad_line_rate": 0.0,
        "duplicate_chapter_count": 0,
        "missing_chapter_count": 0,
        "chapter_order_error_count": 0,
        "truncated_risk": 0,
        "quality_score": score,
        "quality_level": "excellent",
        "quality_reasons_json": "[]",
        "status": "active",
        "reading_status": None,
        "created_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-02 00:00:00",
    }


def add_chapters(db, book_id, names=("第1章", "第2章", "第3章")):
    replace_chapters(
        db,
        book_id,
        [
            {
                "chapter_index": i,
                "chapter_no": i,
                "chapter_type": "chapter",
                "title_raw": name,
                "title_norm": name,
                "start_offset": 0,
                "end_offset": 10,
                "char_count": 10,
                "body_clean_sha256": "x",
                "is_duplicate_suspect": 0,
                "is_missing_suspect": 0,
                "order_status": "ok",
            }
            for i, name in enumerate(names, 1)
        ],
    )


def test_simhash_similarity_and_empty_text():
    same_a = text_simhash("第一章 正文内容" * 20)
    same_b = text_simhash("第一章 正文内容" * 20)
    diff = text_simhash("完全不同的技术文档" * 20)
    assert simhash_similarity(same_a, same_b) == 1.0
    assert simhash_similarity(same_a, diff) < 0.9
    assert isinstance(text_simhash(""), int)


def test_chunk_jaccard_cases():
    text = "A" * 1200 + "B" * 1200
    partial = "A" * 1200 + "C" * 1200
    assert jaccard_similarity(chunk_hashes(text), chunk_hashes(text)) == 1.0
    assert jaccard_similarity(chunk_hashes(text), chunk_hashes(partial)) > 0
    assert jaccard_similarity(chunk_hashes("A" * 1200), chunk_hashes("Z" * 1200)) == 0


def test_title_and_author_similarity():
    assert title_similarity("书名.txt", "书名 精校版.txt") > 0.8
    assert title_similarity("书名A", "完全不同") < 0.8
    assert author_similarity("甲", "甲") == 1.0
    assert author_similarity("甲", "乙") == 0.0


def test_same_work_score_high_and_risks():
    with conn() as db:
        a = upsert_book(db, make_book("A.txt", raw="1", clean="1"))
        b = upsert_book(db, make_book("B.txt", raw="2", clean="2"))
        add_chapters(db, a)
        add_chapters(db, b)
        rows = [dict(db.execute("SELECT * FROM books WHERE id = ?", (x,)).fetchone()) for x in (a, b)]
        result = compare_books(db, rows[0], rows[1], text_lookup=lambda _: "正文内容" * 1000)
    assert result["same_work_score"] >= 0.9
    assert result["confidence_level"] == "high_confidence"
    assert result["risk_flags"] == []


def test_author_conflict_and_length_gap_risks():
    with conn() as db:
        a = upsert_book(db, make_book("A.txt", author="甲", raw="1", clean="1", chars=10000, chapters=10))
        b = upsert_book(db, make_book("B.txt", author="乙", raw="2", clean="2", chars=100000, chapters=20))
        add_chapters(db, a, tuple(f"第{i}章" for i in range(1, 11)))
        add_chapters(db, b, tuple(f"第{i}章" for i in range(1, 21)))
        rows = [dict(db.execute("SELECT * FROM books WHERE id = ?", (x,)).fetchone()) for x in (a, b)]
        result = compare_books(db, rows[0], rows[1], text_lookup=lambda _: "正文内容" * 1000)
    assert "author_conflict" in result["risk_flags"]
    assert "length_gap_large" in result["risk_flags"] or "possible_update_version" in result["risk_flags"]


def test_find_near_default_report_and_apply_behaviour():
    with conn() as db:
        a = upsert_book(db, make_book("A.txt", raw="1", clean="1"))
        b = upsert_book(db, make_book("B.txt", raw="2", clean="2"))
        add_chapters(db, a)
        add_chapters(db, b)
        groups = find_near_duplicates(db, text_lookup=lambda _: "正文内容" * 1000)
        assert groups
        assert db.execute("SELECT COUNT(*) FROM duplicate_groups").fetchone()[0] == 0
        apply_near_duplicates(db, groups)
        assert db.execute("SELECT COUNT(*) FROM duplicate_groups WHERE group_type = 'near_duplicate'").fetchone()[0] == 1


def test_apply_to_work_groups_only_high_confidence_no_risk():
    with conn() as db:
        a = upsert_book(db, make_book("A.txt", raw="1", clean="1"))
        b = upsert_book(db, make_book("B.txt", raw="2", clean="2"))
        add_chapters(db, a)
        add_chapters(db, b)
        groups = find_near_duplicates(db, text_lookup=lambda _: "正文内容" * 1000)
        applied = apply_near_to_work_groups(db, groups)
        assert applied
        assert db.execute("SELECT COUNT(*) FROM work_groups").fetchone()[0] == 1


def test_duplicate_report_contains_near_fields():
    root = repo()
    with conn() as db:
        a = upsert_book(db, make_book("A.txt", raw="1", clean="1"))
        b = upsert_book(db, make_book("B.txt", raw="2", clean="2"))
        add_chapters(db, a)
        add_chapters(db, b)
        groups = find_near_duplicates(db, text_lookup=lambda _: "正文内容" * 1000)
    html, js = generate_duplicate_report(root, groups)
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["groups"][0]["group_type"] == "near_duplicate"
    assert "similarity_breakdown" in data["groups"][0]
    assert "risk_flags" in data["groups"][0]
    assert "near_duplicate" in html.read_text(encoding="utf-8")


def test_summary_report_counts_near_duplicate():
    root = repo()
    payload = {
        "generated_at": "x",
        "groups": [
            {
                "group_type": "near_duplicate",
                "confidence_level": "probable_duplicate",
                "risk_flags": ["possible_update_version"],
                "manual_review": True,
                "recommended_action": "manual_review",
            }
        ],
    }
    (root / "reports" / "duplicate" / "duplicate_report_x.json").write_text(json.dumps(payload), encoding="utf-8")
    output = generate_summary_report(root)
    text = output.read_text(encoding="utf-8")
    assert "near_duplicate" in text
    assert "possible_update_version" in text


def test_find_duplicates_near_zero_hint(capsys, monkeypatch):
    monkeypatch.setattr("novel_manager.cli.repo_path", lambda value: Path(value))
    monkeypatch.setattr("novel_manager.cli.connect", lambda repo: conn())
    monkeypatch.setattr("novel_manager.cli.find_near_duplicates", lambda *args, **kwargs: [])
    monkeypatch.setattr("novel_manager.cli.generate_duplicate_report", lambda repo, groups: (Path("a.html"), Path("a.json")))
    code = main(["find-duplicates", "--repo", "X", "--mode", "near", "--area", "all"])
    out = capsys.readouterr().out
    assert code == 0
    assert "diagnose-near" in out
