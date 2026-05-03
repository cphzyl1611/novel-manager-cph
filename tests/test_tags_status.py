import json
import sqlite3
import uuid
from pathlib import Path

from novel_manager.book_viewer import inspect_book, list_books
from novel_manager.db import initialize, upsert_book
from novel_manager.summary_report import generate_summary_report
from novel_manager.tag_manager import (
    auto_tag,
    books_by_status,
    books_by_tag,
    create_tag,
    delete_tag,
    initialize_default_tags,
    list_tags,
    set_reading_status,
    tag_book,
    untag_book,
)


def conn():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    initialize(db)
    return db


def make_repo() -> Path:
    repo = Path(".tmp") / "tag_status_tests" / uuid.uuid4().hex
    for rel in ["library", "incoming", "reports/summary", "logs"]:
        (repo / rel).mkdir(parents=True, exist_ok=True)
    return repo


def book_payload(path: Path, *, title: str = "测试书", area: str = "library", score: float = 80, ads: int = 0, mojibake: float = 0.0, missing: int = 0, duplicate: int = 0, order: int = 0):
    path.write_text("content", encoding="utf-8")
    return {
        "current_path": str(path),
        "original_path": str(path),
        "repo_area": area,
        "file_name": path.name,
        "file_size": path.stat().st_size,
        "mtime": 1.0,
        "raw_sha256": "raw-" + path.name,
        "clean_sha256": "clean-" + path.name,
        "title_raw": title,
        "title_norm": title,
        "author_raw": "作者",
        "author_norm": "作者",
        "encoding": "utf-8",
        "encoding_confidence": 1.0,
        "decode_status": "ok",
        "char_count_raw": 100,
        "char_count_clean": 100,
        "line_count_raw": 10,
        "line_count_clean": 10,
        "chapter_count": 2,
        "mojibake_rate": mojibake,
        "ad_line_count": ads,
        "ad_line_rate": 0.03 if ads >= 50 else 0.0,
        "duplicate_chapter_count": duplicate,
        "missing_chapter_count": missing,
        "chapter_order_error_count": order,
        "truncated_risk": 0,
        "quality_score": score,
        "quality_level": "poor" if score < 60 else "good",
        "quality_reasons_json": json.dumps(["reason"], ensure_ascii=False),
        "status": "active",
        "reading_status": None,
        "created_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-02 00:00:00",
    }


def seed_book(db, repo: Path, name="book.txt", **kwargs) -> int:
    area = kwargs.pop("area", "library")
    return upsert_book(db, book_payload(repo / area / name, area=area, **kwargs))


def test_default_tags_idempotent():
    with conn() as db:
        first = len(list_tags(db))
        initialize_default_tags(db)
        second = len(list_tags(db))
    assert first >= 30
    assert first == second


def test_list_create_delete_tag():
    repo = make_repo()
    with conn() as db:
        bid = seed_book(db, repo)
        result = create_tag(db, repo, name="克苏鲁", category="genre", description="克苏鲁题材")
        assert result["status"] == "created"
        assert create_tag(db, repo, name="克苏鲁")["status"] == "exists"
        tag_book(db, repo, book_id=bid, tag="克苏鲁")
        assert list_tags(db, category="genre", query="克苏鲁")[0]["book_count"] == 1
        dry = delete_tag(db, repo, tag="克苏鲁", dry_run=True)
        assert dry["book_count"] == 1
        assert list_tags(db, query="克苏鲁")
        delete_tag(db, repo, tag="克苏鲁", confirm=True)
        assert not list_tags(db, query="克苏鲁")
        assert db.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 1


def test_tag_untag_books_by_tag():
    repo = make_repo()
    with conn() as db:
        library_id = seed_book(db, repo, "a.txt", area="library")
        incoming_id = seed_book(db, repo, "b.txt", area="incoming")
        assert tag_book(db, repo, book_id=library_id, tag="自定义")["status"] == "tag_not_found"
        assert tag_book(db, repo, book_id=library_id, tag="自定义", create=True)["status"] == "tagged"
        assert tag_book(db, repo, book_id=library_id, tag="自定义")["status"] == "exists"
        tag_book(db, repo, book_id=incoming_id, tag="自定义")
        assert len(books_by_tag(db, tag="自定义", area="library")) == 1
        assert len(books_by_tag(db, tag="自定义", area="incoming")) == 1
        assert untag_book(db, repo, book_id=library_id, tag="自定义")["status"] == "untagged"
        assert list_tags(db, query="自定义")


def test_status_and_books_by_status():
    repo = make_repo()
    with conn() as db:
        bid = seed_book(db, repo)
        assert set_reading_status(db, repo, book_id=bid, status="非法")["status"] == "invalid_status"
        assert set_reading_status(db, repo, book_id=bid, status="自定义", allow_custom_status=True)["status"] == "updated"
        assert set_reading_status(db, repo, book_id=bid, status="已读")["status"] == "updated"
        assert len(books_by_status(db, status="已读")) == 1


def test_auto_tag_dry_run_and_apply_rules():
    repo = make_repo()
    with conn() as db:
        seed_book(db, repo, "精校完本.txt", score=95)
        unfinished_id = seed_book(db, repo, "连载未完结.txt", score=80)
        seed_book(db, repo, "bad.txt", score=50, ads=60, mojibake=0.01, missing=1, duplicate=1, order=1)
        dry = auto_tag(db, repo, dry_run=True)
        assert dry["suggestions"]
        assert db.execute("SELECT COUNT(*) FROM book_tags").fetchone()[0] == 0
        applied = auto_tag(db, repo, apply=True)
        assert applied["applied"] > 0
        unfinished_tags = {
            row["name"]
            for row in db.execute(
                "SELECT t.name FROM tags t JOIN book_tags bt ON bt.tag_id = t.id WHERE bt.book_id = ?",
                (unfinished_id,),
            ).fetchall()
        }
        assert "未完结" in unfinished_tags
        assert "完本" not in unfinished_tags
        names = {row["name"] for row in list_tags(db)}
        assert {"精校", "完本", "广告较多", "疑似乱码", "疑似缺章", "章节异常", "低质量", "高质量"} <= names
        assert db.execute("SELECT COUNT(*) FROM book_tags WHERE source = 'auto'").fetchone()[0] > 0


def test_list_books_inspect_book_and_summary_include_tags_status():
    repo = make_repo()
    with conn() as db:
        bid = seed_book(db, repo)
        tag_book(db, repo, book_id=bid, tag="玄幻")
        set_reading_status(db, repo, book_id=bid, status="未读")
        listed = list_books(db, tag="玄幻", status="未读")
        assert listed["shown"] == 1
        assert listed["rows"][0]["tag_names"] == ["玄幻"]
        inspected = inspect_book(db, book_id=bid)
        assert inspected["book"]["reading_status"] == "未读"
        assert inspected["tags"][0]["name"] == "玄幻"
    db_path = repo / "db" / "novel_repo.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    file_db = sqlite3.connect(db_path)
    file_db.row_factory = sqlite3.Row
    initialize(file_db)
    bid = seed_book(file_db, repo, "summary.txt")
    tag_book(file_db, repo, book_id=bid, tag="玄幻")
    set_reading_status(file_db, repo, book_id=bid, status="未读")
    file_db.close()
    text = generate_summary_report(repo).read_text(encoding="utf-8")
    assert "标签与阅读状态汇总" in text
