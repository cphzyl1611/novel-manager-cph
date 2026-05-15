"""Tests for external_removed status and health center missing file handling."""
from __future__ import annotations

import tempfile
from pathlib import Path

from novel_manager.db import connect as db_connect, initialize
from novel_manager.server.services.health_service import (
    get_health_summary,
    list_health_issues,
    mark_book_external_removed,
    unmark_book_external_removed,
)
from novel_manager.server.services.book_service import list_books
from novel_manager.server.services.sync_service import get_sync_manifest, get_sync_snapshot


def _make_repo_with_missing_file() -> Path:
    """Create a temporary repo with a book whose file is missing."""
    repo = Path(tempfile.mkdtemp())
    (repo / "library").mkdir()
    (repo / "incoming").mkdir()
    (repo / "db").mkdir()

    conn = db_connect(repo)
    initialize(conn)

    # Add a book with a path that doesn't exist
    missing_path = str(repo / "library" / "missing_book.txt")
    conn.execute(
        """INSERT INTO books
           (current_path, title_raw, title_norm, author_raw, author_norm,
            file_size, raw_sha256, clean_sha256, chapter_count, quality_score,
            quality_level, repo_area, status, file_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            missing_path,
            "缺失的小说",
            "缺失的小说",
            "作者",
            "作者",
            100000,
            "sha256_missing",
            "sha256_clean_missing",
            100,
            85.0,
            "good",
            "library",
            None,  # status is NULL initially
            "missing_book.txt",
        ),
    )

    # Add a normal book with existing file
    existing_path = repo / "library" / "existing_book.txt"
    existing_path.write_text("内容", encoding="utf-8")
    conn.execute(
        """INSERT INTO books
           (current_path, title_raw, title_norm, author_raw, author_norm,
            file_size, raw_sha256, clean_sha256, chapter_count, quality_score,
            quality_level, repo_area, status, file_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(existing_path),
            "存在的小说",
            "存在的小说",
            "作者",
            "作者",
            100000,
            "sha256_existing",
            "sha256_clean_existing",
            100,
            85.0,
            "good",
            "library",
            None,
            "existing_book.txt",
        ),
    )

    conn.commit()
    conn.close()

    return repo


def test_missing_file_detected_in_health_issues():
    """Test that missing file is detected as error in health issues."""
    repo = _make_repo_with_missing_file()
    try:
        issues = list_health_issues(str(repo))
        items = issues.get("items", [])

        # Should have missing_file error
        missing_items = [i for i in items if i["code"] == "missing_file"]
        assert len(missing_items) >= 1
        assert missing_items[0]["severity"] == "error"
    finally:
        import shutil
        shutil.rmtree(repo)


def test_missing_file_counted_in_summary():
    """Test that missing file is counted in health summary."""
    repo = _make_repo_with_missing_file()
    try:
        summary = get_health_summary(str(repo))
        integrity = summary.get("integrity", {})
        assert integrity.get("missing_files", 0) >= 1
    finally:
        import shutil
        shutil.rmtree(repo)


def test_external_removed_not_counted_as_missing():
    """Test that external_removed books are not counted as missing."""
    repo = _make_repo_with_missing_file()
    try:
        conn = db_connect(repo)
        # Mark the missing book as external_removed
        conn.execute(
            "UPDATE books SET status = 'external_removed' WHERE title_norm = '缺失的小说'"
        )
        conn.commit()
        conn.close()

        summary = get_health_summary(str(repo))
        integrity = summary.get("integrity", {})
        # missing_files should be 0 now
        assert integrity.get("missing_files", 0) == 0
        # external_removed_count should be 1
        assert integrity.get("external_removed_count", 0) == 1
    finally:
        import shutil
        shutil.rmtree(repo)


def test_external_removed_shown_as_info_not_error():
    """Test that external_removed books show as info, not error."""
    repo = _make_repo_with_missing_file()
    try:
        conn = db_connect(repo)
        conn.execute(
            "UPDATE books SET status = 'external_removed' WHERE title_norm = '缺失的小说'"
        )
        conn.commit()
        conn.close()

        issues = list_health_issues(str(repo))
        items = issues.get("items", [])

        # Should have known_missing info, not missing_file error
        known_items = [i for i in items if i["code"] == "known_missing"]
        assert len(known_items) >= 1
        assert known_items[0]["severity"] == "info"
        assert known_items[0]["status"] == "external_removed"

        # Should NOT have missing_file error
        missing_items = [i for i in items if i["code"] == "missing_file"]
        assert len(missing_items) == 0
    finally:
        import shutil
        shutil.rmtree(repo)


def test_mark_removed_api_success():
    """Test mark-removed API successfully sets status."""
    repo = _make_repo_with_missing_file()
    try:
        conn = db_connect(repo)
        book_id = conn.execute(
            "SELECT id FROM books WHERE title_norm = '缺失的小说'"
        ).fetchone()["id"]
        conn.close()

        result = mark_book_external_removed(str(repo), book_id)
        assert result["ok"] is True
        assert result["status"] == "external_removed"

        # Verify status in database
        conn = db_connect(repo)
        status = conn.execute(
            "SELECT status FROM books WHERE id = ?", (book_id,)
        ).fetchone()["status"]
        assert status == "external_removed"
        conn.close()
    finally:
        import shutil
        shutil.rmtree(repo)


def test_mark_removed_does_not_delete_file():
    """Test mark-removed does not delete any file."""
    repo = _make_repo_with_missing_file()
    try:
        # The file is already missing, but we verify no new deletions
        existing_path = repo / "library" / "existing_book.txt"
        assert existing_path.exists()

        conn = db_connect(repo)
        book_id = conn.execute(
            "SELECT id FROM books WHERE title_norm = '缺失的小说'"
        ).fetchone()["id"]
        conn.close()

        mark_book_external_removed(str(repo), book_id)

        # Existing file should still exist
        assert existing_path.exists()
    finally:
        import shutil
        shutil.rmtree(repo)


def test_mark_removed_excluded_from_books_list():
    """Test that external_removed books are excluded from books list by default."""
    repo = _make_repo_with_missing_file()
    try:
        conn = db_connect(repo)
        book_id = conn.execute(
            "SELECT id FROM books WHERE title_norm = '缺失的小说'"
        ).fetchone()["id"]
        conn.close()

        # Before marking, should be in list
        before = list_books(str(repo))
        assert before["total"] == 2

        # Mark as removed
        mark_book_external_removed(str(repo), book_id)

        # After marking, should be excluded
        after = list_books(str(repo))
        assert after["total"] == 1

        # Can include with include_removed=True
        with_removed = list_books(str(repo), include_removed=True)
        assert with_removed["total"] == 2
    finally:
        import shutil
        shutil.rmtree(repo)


def test_mark_removed_excluded_from_sync_snapshot():
    """Test that external_removed books are excluded from sync snapshot."""
    repo = _make_repo_with_missing_file()
    try:
        conn = db_connect(repo)
        book_id = conn.execute(
            "SELECT id FROM books WHERE title_norm = '缺失的小说'"
        ).fetchone()["id"]
        conn.close()

        # Before marking
        before = get_sync_snapshot(str(repo))
        assert len(before["books"]) == 2

        # Mark as removed
        mark_book_external_removed(str(repo), book_id)

        # After marking
        after = get_sync_snapshot(str(repo))
        assert len(after["books"]) == 1

        # Manifest stats should also reflect this
        manifest = get_sync_manifest(str(repo))
        assert manifest["library_stats"]["total_books"] == 1
    finally:
        import shutil
        shutil.rmtree(repo)


def test_unmark_removed_restores_status():
    """Test unmark-removed restores status to normal."""
    repo = _make_repo_with_missing_file()
    try:
        conn = db_connect(repo)
        book_id = conn.execute(
            "SELECT id FROM books WHERE title_norm = '缺失的小说'"
        ).fetchone()["id"]
        conn.close()

        # Mark first
        mark_book_external_removed(str(repo), book_id)

        # Unmark
        result = unmark_book_external_removed(str(repo), book_id)
        assert result["ok"] is True
        assert result["status"] == "normal"

        # Verify status in database
        conn = db_connect(repo)
        status = conn.execute(
            "SELECT status FROM books WHERE id = ?", (book_id,)
        ).fetchone()["status"]
        assert status == "normal"
        conn.close()
    finally:
        import shutil
        shutil.rmtree(repo)


def test_unmark_removed_file_still_missing_shows_warning():
    """Test that after unmark, missing file warning reappears."""
    repo = _make_repo_with_missing_file()
    try:
        conn = db_connect(repo)
        book_id = conn.execute(
            "SELECT id FROM books WHERE title_norm = '缺失的小说'"
        ).fetchone()["id"]
        conn.close()

        # Mark first
        mark_book_external_removed(str(repo), book_id)

        # Verify no missing_file error
        issues_before = list_health_issues(str(repo))
        missing_before = [i for i in issues_before["items"] if i["code"] == "missing_file"]
        assert len(missing_before) == 0

        # Unmark
        unmark_book_external_removed(str(repo), book_id)

        # Now missing_file should reappear
        issues_after = list_health_issues(str(repo))
        missing_after = [i for i in issues_after["items"] if i["code"] == "missing_file"]
        assert len(missing_after) >= 1
        assert missing_after[0]["severity"] == "error"
    finally:
        import shutil
        shutil.rmtree(repo)


def test_normal_existing_book_unaffected():
    """Test that normal existing books are unaffected by all this."""
    repo = _make_repo_with_missing_file()
    try:
        # Get health issues
        issues = list_health_issues(str(repo))
        items = issues.get("items", [])

        # Existing book should NOT appear in issues
        existing_items = [i for i in items if "existing_book" in i.get("file_name", "")]
        assert len(existing_items) == 0

        # Existing book should be in books list
        books = list_books(str(repo))
        existing_books = [b for b in books["items"] if b["title"] == "存在的小说"]
        assert len(existing_books) == 1
    finally:
        import shutil
        shutil.rmtree(repo)


def test_mark_removed_nonexistent_book_fails():
    """Test that marking nonexistent book fails."""
    repo = _make_repo_with_missing_file()
    try:
        result = mark_book_external_removed(str(repo), 99999)
        assert result["ok"] is False
        assert result["error_code"] == "book_not_found"
    finally:
        import shutil
        shutil.rmtree(repo)


def test_unmark_non_external_removed_book_is_ok():
    """Test that unmarking a book that isn't external_removed is ok."""
    repo = _make_repo_with_missing_file()
    try:
        conn = db_connect(repo)
        book_id = conn.execute(
            "SELECT id FROM books WHERE title_norm = '存在的小说'"
        ).fetchone()["id"]
        conn.close()

        # This book has status=NULL, not external_removed
        result = unmark_book_external_removed(str(repo), book_id)
        assert result["ok"] is True
        # Should return current status
        assert result["status"] == "normal" or result["status"] is None
    finally:
        import shutil
        shutil.rmtree(repo)


def test_operation_record_created_on_mark_removed():
    """Test that operation record is created when marking removed."""
    repo = _make_repo_with_missing_file()
    try:
        conn = db_connect(repo)
        book_id = conn.execute(
            "SELECT id FROM books WHERE title_norm = '缺失的小说'"
        ).fetchone()["id"]
        conn.close()

        # Mark removed
        mark_book_external_removed(str(repo), book_id)

        # Check operation record
        conn = db_connect(repo)
        ops = conn.execute(
            "SELECT * FROM web_operation_records WHERE operation_type = 'mark_external_removed'"
        ).fetchall()
        assert len(ops) >= 1
        assert ops[0]["book_id"] == book_id
        assert ops[0]["reversible"] == 1
        conn.close()
    finally:
        import shutil
        shutil.rmtree(repo)


def test_operation_record_created_on_unmark_removed():
    """Test that operation record is created when unmarking."""
    repo = _make_repo_with_missing_file()
    try:
        conn = db_connect(repo)
        book_id = conn.execute(
            "SELECT id FROM books WHERE title_norm = '缺失的小说'"
        ).fetchone()["id"]
        conn.close()

        # Mark first
        mark_book_external_removed(str(repo), book_id)

        # Unmark
        unmark_book_external_removed(str(repo), book_id)

        # Check operation record
        conn = db_connect(repo)
        ops = conn.execute(
            "SELECT * FROM web_operation_records WHERE operation_type = 'unmark_external_removed'"
        ).fetchall()
        assert len(ops) >= 1
        assert ops[0]["book_id"] == book_id
        conn.close()
    finally:
        import shutil
        shutil.rmtree(repo)