"""Tests for Legado BookSource API."""
import tempfile
from pathlib import Path
from novel_manager.db import connect as db_connect, initialize
from novel_manager.server.services.legado_service import (
    book_info, build_source_json, get_content, get_toc, search_books,
)

def _make_repo():
    repo = Path(tempfile.mkdtemp())
    (repo / "library").mkdir(); (repo / "db").mkdir()
    conn = db_connect(repo); initialize(conn)
    b1 = repo / "library" / "b1.txt"
    b1.write_text("Chapter 1\nContent one.\nChapter 2\nContent two.", encoding="utf-8")
    (repo / "library" / "b2.txt").write_text("Book two content.", encoding="utf-8")
    conn.executemany(
        "INSERT INTO books (id, current_path, title_raw, title_norm, author_norm, repo_area, status, chapter_count, file_name, quality_score) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(1, str(b1), "测试A", "测试A", "作者A", "library", None, 2, "b1.txt", 85.0),
         (2, str(repo / "library" / "b2.txt"), "测试B", "测试B", "作者B", "library", None, 1, "b2.txt", 90.0)],
    )
    conn.commit(); conn.close()
    return repo

def test_search_returns_items():
    repo = _make_repo()
    try: r = search_books(str(repo)); assert len(r["items"]) == 2
    finally: import shutil; shutil.rmtree(repo)

def test_search_filters():
    repo = _make_repo()
    try: r = search_books(str(repo), key="B"); assert len(r["items"]) == 1
    finally: import shutil; shutil.rmtree(repo)

def test_book_info_ok():
    repo = _make_repo()
    try: r = book_info(str(repo), 1); assert r and r["title"] == "测试A"
    finally: import shutil; shutil.rmtree(repo)

def test_book_info_nonexistent():
    repo = _make_repo()
    try: assert book_info(str(repo), 999) is None
    finally: import shutil; shutil.rmtree(repo)

def test_toc_ok():
    repo = _make_repo()
    try: r = get_toc(str(repo), 1); assert r and "chapters" in r
    finally: import shutil; shutil.rmtree(repo)

def test_content_ok():
    repo = _make_repo()
    try: r = get_content(str(repo), 1, 0); assert r and len(r["content"]) > 0
    finally: import shutil; shutil.rmtree(repo)

def test_source_json():
    r = build_source_json("192.168.1.100:8765")
    assert r["bookSourceName"] == "NovelHub"
    assert "局域网" in r["bookSourceGroup"]
    assert "ruleSearch" in r and "ruleToc" in r and "ruleContent" in r
    assert "192.168.1.100" in r["ruleSearch"]["searchUrl"]
