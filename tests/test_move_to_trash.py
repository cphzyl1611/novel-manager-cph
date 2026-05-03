import sqlite3
import uuid
from pathlib import Path

import pytest

from novel_manager.cli import main
from novel_manager.db import initialize, upsert_book
from novel_manager.move_to_trash import move_book_to_trash, write_move_to_trash_log


def make_repo() -> Path:
    root = Path(".tmp") / "move_to_trash_tests" / uuid.uuid4().hex
    for rel in ["library", "trash", "logs"]:
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize(conn)
    return conn


def book(path: Path) -> dict:
    return {
        "current_path": str(path),
        "original_path": str(path),
        "repo_area": "library",
        "file_name": path.name,
        "file_size": path.stat().st_size if path.exists() else 0,
        "mtime": 1.0,
        "raw_sha256": "raw-" + path.name,
        "clean_sha256": "clean-" + path.name,
        "title_raw": "书",
        "title_norm": "书",
        "author_raw": "",
        "author_norm": "",
        "encoding": "utf-8",
        "encoding_confidence": 1.0,
        "decode_status": "ok",
        "char_count_raw": 10,
        "char_count_clean": 10,
        "line_count_raw": 1,
        "line_count_clean": 1,
        "chapter_count": 1,
        "mojibake_rate": 0,
        "ad_line_count": 0,
        "ad_line_rate": 0,
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


def seed(conn, repo, name="book.txt", content="content"):
    path = repo / "library" / name
    path.write_text(content, encoding="utf-8")
    return upsert_book(conn, book(path)), path


def test_dry_run_does_not_move_or_update_db():
    repo = make_repo()
    with memory_conn() as conn:
        book_id, path = seed(conn, repo)
        result = move_book_to_trash(conn, repo, book_id, dry_run=True)
        row = conn.execute("SELECT repo_area, status, current_path FROM books WHERE id = ?", (book_id,)).fetchone()
        ops = conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
    assert result["status"] == "dry_run"
    assert path.exists()
    assert row["repo_area"] == "library"
    assert row["status"] == "active"
    assert ops == 0


def test_confirm_moves_to_trash_updates_db_operations_and_log():
    repo = make_repo()
    with memory_conn() as conn:
        book_id, path = seed(conn, repo)
        result = move_book_to_trash(conn, repo, book_id, confirm=True)
        log = write_move_to_trash_log(repo, result)
        row = conn.execute("SELECT repo_area, status, current_path, file_name FROM books WHERE id = ?", (book_id,)).fetchone()
        op = conn.execute("SELECT operation_type, status FROM operations").fetchone()
    target = Path(result["target_path"])
    assert result["status"] == "success"
    assert not path.exists()
    assert target.exists()
    assert target.parent == repo / "trash"
    assert row["repo_area"] == "trash"
    assert row["status"] == "trashed"
    assert row["file_name"] == target.name
    assert op["operation_type"] == "move_to_trash"
    assert op["status"] == "success"
    assert log.exists()
    assert "move_to_trash" in (repo / "logs" / "operations.log").read_text(encoding="utf-8")


def test_confirm_does_not_overwrite_same_name():
    repo = make_repo()
    (repo / "trash" / "book.txt").write_text("old", encoding="utf-8")
    with memory_conn() as conn:
        book_id, _ = seed(conn, repo, "book.txt", "new")
        result = move_book_to_trash(conn, repo, book_id, confirm=True)
    assert Path(result["target_path"]).name != "book.txt"
    assert Path(result["target_path"]).exists()
    assert (repo / "trash" / "book.txt").read_text(encoding="utf-8") == "old"


def test_cli_safety_gate_and_missing_file(capsys):
    assert main(["move-to-trash", "--repo", "X", "--book-id", "1"]) == 2
    assert main(["move-to-trash", "--repo", "X", "--book-id", "1", "--confirm"]) == 2
    with pytest.raises(SystemExit):
        main(["move-to-trash", "--repo", "X", "--book-id", "1", "--dry-run", "--confirm"])
    repo = make_repo()
    db = repo / "db"
    db.mkdir()
    conn = sqlite3.connect(repo / "db" / "novel_repo.sqlite")
    conn.row_factory = sqlite3.Row
    initialize(conn)
    missing = repo / "library" / "missing.txt"
    book_id = upsert_book(conn, book(missing))
    conn.close()
    assert main(["move-to-trash", "--repo", str(repo), "--book-id", str(book_id), "--dry-run"]) == 1
