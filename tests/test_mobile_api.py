"""Tests for mobile API endpoints."""
from __future__ import annotations

import tempfile
from pathlib import Path

from novel_manager.db import connect as db_connect, initialize
from novel_manager.server.services.mobile_service import (
    get_mobile_books,
    get_mobile_chapters,
    get_mobile_chapter_content,
    save_mobile_progress,
)


def _make_repo():
    repo = Path(tempfile.mkdtemp())
    (repo / "library").mkdir()
    (repo / "incoming").mkdir()
    (repo / "db").mkdir()
    conn = db_connect(repo)
    initialize(conn)
    book1 = repo / "library" / "book1.txt"
    book1.write_text("Chapter 1\nContent of chapter one.\nChapter 2\nContent of chapter two.", encoding="utf-8")
    book2 = repo / "library" / "book2.txt"
    book2.write_text("Chapter 1\nContent.\nChapter 2\nMore.\nChapter 3\nEnd.", encoding="utf-8")
    (repo / "incoming" / "inc.txt").write_text("incoming book", encoding="utf-8")
    conn.executemany(
        "INSERT INTO books (id, current_path, title_raw, title_norm, author_norm, repo_area, status, chapter_count, file_name, quality_score) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(1, str(book1), "Test Book 1", "Test Book 1", "Author1", "library", None, 2, "book1.txt", 85.0),
         (2, str(book2), "Test Book 2", "Test Book 2", "Author2", "library", None, 3, "book2.txt", 90.0),
         (3, str(repo / "incoming" / "inc.txt"), "Inc", "Inc", "A", "incoming", None, 1, "inc.txt", 50.0),
         (4, str(repo / "library" / "missing.txt"), "Missing", "Missing", "X", "library", "external_removed", 1, "missing.txt", 0.0)],
    )
    conn.commit(); conn.close()
    return repo


def test_mobile_books_only_library():
    repo = _make_repo()
    try:
        items = get_mobile_books(str(repo))["items"]
        assert len(items) == 2
        assert {i["title"] for i in items} == {"Test Book 1", "Test Book 2"}
    finally:
        import shutil; shutil.rmtree(repo)


def test_mobile_books_excludes_incoming():
    repo = _make_repo()
    try:
        items = get_mobile_books(str(repo))["items"]
        assert "Inc" not in {i["title"] for i in items}
    finally:
        import shutil; shutil.rmtree(repo)


def test_mobile_books_excludes_external_removed():
    repo = _make_repo()
    try:
        items = get_mobile_books(str(repo))["items"]
        assert "Missing" not in {i["title"] for i in items}
    finally:
        import shutil; shutil.rmtree(repo)


def test_mobile_books_has_server_revision():
    repo = _make_repo()
    try:
        assert "server_revision" in get_mobile_books(str(repo))
    finally:
        import shutil; shutil.rmtree(repo)


def test_mobile_chapters_returns_list():
    repo = _make_repo()
    try:
        result = get_mobile_chapters(str(repo), 1)
        assert result is not None and result["book_id"] == 1
    finally:
        import shutil; shutil.rmtree(repo)


def test_mobile_chapter_not_full_book():
    repo = _make_repo()
    try:
        result = get_mobile_chapter_content(str(repo), 1, 0)
        assert result is not None
        content = result["content"]
        assert len(content) > 0
        assert len(content) < 200  # Single chapter, not full book
    finally:
        import shutil; shutil.rmtree(repo)


def test_mobile_progress_saves():
    repo = _make_repo()
    try:
        r = save_mobile_progress(str(repo), {"book_id": 1, "chapter_index": 0, "progress_ratio": 0.5, "device_id": "test"})
        assert r["ok"] is True
    finally:
        import shutil; shutil.rmtree(repo)


def test_mobile_api_no_file_ops():
    repo = _make_repo()
    try:
        book1 = repo / "library" / "book1.txt"
        original = book1.read_text(encoding="utf-8")
        get_mobile_books(str(repo))
        get_mobile_chapters(str(repo), 1)
        get_mobile_chapter_content(str(repo), 1, 0)
        save_mobile_progress(str(repo), {"book_id": 1, "chapter_index": 0, "progress_ratio": 0.3})
        assert book1.read_text(encoding="utf-8") == original
        assert book1.exists()
    finally:
        import shutil; shutil.rmtree(repo)
