"""Tests for sync API endpoints."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from novel_manager.db import connect as db_connect, initialize
from novel_manager.server.services.sync_service import (
    get_sync_manifest,
    get_sync_snapshot,
    get_sync_changes,
    sync_upload_progress,
    sync_download_progress,
)


def _make_repo() -> Path:
    """Create a temporary repo with test data."""
    repo = Path(tempfile.mkdtemp())
    (repo / "library").mkdir()
    (repo / "incoming").mkdir()
    (repo / "db").mkdir()

    conn = db_connect(repo)
    initialize(conn)

    # Add test books
    conn.execute(
        """INSERT INTO books
           (current_path, title_raw, title_norm, author_raw, author_norm,
            file_size, raw_sha256, clean_sha256, chapter_count, quality_score,
            quality_level, repo_area, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "library/book1.txt",
            "测试小说一",
            "测试小说一",
            "作者A",
            "作者a",
            100000,
            "sha256_aaa",
            "sha256_clean_aaa",
            100,
            85.0,
            "good",
            "library",
            "active",
        ),
    )
    conn.execute(
        """INSERT INTO books
           (current_path, title_raw, title_norm, author_raw, author_norm,
            file_size, raw_sha256, clean_sha256, chapter_count, quality_score,
            quality_level, repo_area, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "library/book2.txt",
            "测试小说二",
            "测试小说二",
            "作者B",
            "作者b",
            200000,
            "sha256_bbb",
            "sha256_clean_bbb",
            200,
            90.0,
            "excellent",
            "library",
            "active",
        ),
    )
    conn.commit()
    conn.close()

    return repo


def test_get_sync_manifest():
    """Test getting sync manifest."""
    repo = _make_repo()
    try:
        manifest = get_sync_manifest(str(repo))

        assert "repo_id" in manifest
        assert len(manifest["repo_id"]) == 8  # UUID[:8]
        assert "server_device_id" in manifest
        assert "desktop-" in manifest["server_device_id"]
        assert manifest["server_revision"] >= 0
        assert manifest["server_version"] == "1.0.0"
        assert manifest["library_stats"]["total_books"] == 2
        assert manifest["library_stats"]["total_chapters"] == 300
    finally:
        import shutil

        shutil.rmtree(repo)


def test_get_sync_manifest_idempotent():
    """Test that manifest returns same repo_id on subsequent calls."""
    repo = _make_repo()
    try:
        manifest1 = get_sync_manifest(str(repo))
        manifest2 = get_sync_manifest(str(repo))

        assert manifest1["repo_id"] == manifest2["repo_id"]
    finally:
        import shutil

        shutil.rmtree(repo)


def test_get_sync_snapshot():
    """Test getting full library snapshot."""
    repo = _make_repo()
    try:
        snapshot = get_sync_snapshot(str(repo))

        assert "manifest" in snapshot
        assert "books" in snapshot
        assert len(snapshot["books"]) == 2

        # Check book data
        book = snapshot["books"][0]
        assert "id" in book
        assert "title_raw" in book
        assert "title_norm" in book
        assert "author_raw" in book
        assert "file_size" in book
        assert "chapter_count" in book
        assert "quality_score" in book

        # Chapters not included by default
        assert "chapters" not in snapshot
    finally:
        import shutil

        shutil.rmtree(repo)


def test_get_sync_snapshot_with_chapters():
    """Test getting snapshot with chapters."""
    repo = _make_repo()
    try:
        conn = db_connect(repo)
        conn.execute(
            """INSERT INTO chapters (book_id, chapter_index, chapter_no, title_raw, title_norm, start_offset, end_offset, char_count)
               VALUES (1, 0, 1, '第一章', '第一章', 0, 1000, 1000)"""
        )
        conn.execute(
            """INSERT INTO chapters (book_id, chapter_index, chapter_no, title_raw, title_norm, start_offset, end_offset, char_count)
               VALUES (1, 1, 2, '第二章', '第二章', 1000, 2000, 1000)"""
        )
        conn.commit()
        conn.close()

        snapshot = get_sync_snapshot(str(repo), include_chapters=True)

        assert "chapters" in snapshot
        assert len(snapshot["chapters"]) == 2
        assert snapshot["chapters"][0]["book_id"] == 1
    finally:
        import shutil

        shutil.rmtree(repo)


def test_get_sync_changes_empty():
    """Test getting changes when none exist."""
    repo = _make_repo()
    try:
        changes = get_sync_changes(str(repo), since_revision=0)

        assert "manifest" in changes
        assert "changes" in changes
        assert "has_more" in changes
        # Initially no changes recorded
        assert len(changes["changes"]) == 0
    finally:
        import shutil

        shutil.rmtree(repo)


def test_sync_upload_progress():
    """Test uploading reading progress."""
    repo = _make_repo()
    try:
        result = sync_upload_progress(
            str(repo),
            "mobile-test-device",
            [
                {"book_id": 1, "progress_ratio": 0.5, "scroll_position": 1000, "current_chapter_index": 5},
                {"book_id": 2, "progress_ratio": 0.8, "scroll_position": 2000, "current_chapter_index": 10},
            ],
        )

        assert result["ok"] is True
        assert result["accepted"] == 2
        assert result["rejected"] == 0
        assert result["server_revision"] >= 1
    finally:
        import shutil

        shutil.rmtree(repo)


def test_sync_upload_progress_invalid_book():
    """Test uploading progress for non-existent book."""
    repo = _make_repo()
    try:
        result = sync_upload_progress(
            str(repo),
            "mobile-test-device",
            [
                {"book_id": 999, "progress_ratio": 0.5, "scroll_position": 1000},
            ],
        )

        assert result["ok"] is True
        assert result["accepted"] == 0
        assert result["rejected"] == 1
    finally:
        import shutil

        shutil.rmtree(repo)


def test_sync_upload_progress_missing_book_id():
    """Test uploading progress without book_id."""
    repo = _make_repo()
    try:
        result = sync_upload_progress(
            str(repo),
            "mobile-test-device",
            [
                {"progress_ratio": 0.5, "scroll_position": 1000},
            ],
        )

        assert result["ok"] is True
        assert result["accepted"] == 0
        assert result["rejected"] == 1
    finally:
        import shutil

        shutil.rmtree(repo)


def test_sync_download_progress():
    """Test downloading reading progress."""
    repo = _make_repo()
    try:
        # First upload some progress
        sync_upload_progress(
            str(repo),
            "mobile-test-device",
            [
                {"book_id": 1, "progress_ratio": 0.5, "scroll_position": 1000, "current_chapter_index": 5},
            ],
        )

        # Then download it
        result = sync_download_progress(str(repo), "mobile-test-device")

        assert result["ok"] is True
        assert len(result["progress"]) == 1
        assert result["progress"][0]["book_id"] == 1
        assert result["progress"][0]["progress_ratio"] == 0.5
        assert result["progress"][0]["scroll_position"] == 1000
        assert result["progress"][0]["current_chapter_index"] == 5
    finally:
        import shutil

        shutil.rmtree(repo)


def test_sync_download_progress_empty():
    """Test downloading progress when none exists."""
    repo = _make_repo()
    try:
        result = sync_download_progress(str(repo), "mobile-test-device")

        assert result["ok"] is True
        assert len(result["progress"]) == 0
    finally:
        import shutil

        shutil.rmtree(repo)


def test_sync_download_progress_different_devices():
    """Test that progress is isolated by device_id."""
    repo = _make_repo()
    try:
        # Upload for device1
        sync_upload_progress(
            str(repo),
            "device1",
            [
                {"book_id": 1, "progress_ratio": 0.3, "scroll_position": 500},
            ],
        )

        # Upload for device2
        sync_upload_progress(
            str(repo),
            "device2",
            [
                {"book_id": 1, "progress_ratio": 0.7, "scroll_position": 1500},
            ],
        )

        # Download for device1
        result1 = sync_download_progress(str(repo), "device1")
        assert result1["progress"][0]["progress_ratio"] == 0.3

        # Download for device2
        result2 = sync_download_progress(str(repo), "device2")
        assert result2["progress"][0]["progress_ratio"] == 0.7
    finally:
        import shutil

        shutil.rmtree(repo)


def test_sync_state_table_created():
    """Test that sync_state table is created automatically."""
    repo = _make_repo()
    try:
        # Call a sync function to trigger table creation
        get_sync_manifest(str(repo))

        conn = db_connect(repo)

        # Check sync_state table exists
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sync_state'"
        ).fetchone()
        assert tables is not None

        # Check sync_changes table exists
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sync_changes'"
        ).fetchone()
        assert tables is not None

        conn.close()
    finally:
        import shutil

        shutil.rmtree(repo)


def test_sync_snapshot_only_library():
    """Test that snapshot only includes library books."""
    repo = _make_repo()
    try:
        # Add an incoming book
        conn = db_connect(repo)
        conn.execute(
            """INSERT INTO books
               (current_path, title_raw, title_norm, author_raw, author_norm,
                file_size, raw_sha256, clean_sha256, chapter_count, quality_score,
                quality_level, repo_area, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "incoming/book3.txt",
                "新下载的书",
                "新下载的书",
                "作者C",
                "作者c",
                50000,
                "sha256_ccc",
                "sha256_clean_ccc",
                50,
                75.0,
                "fair",
                "incoming",
                "active",
            ),
        )
        conn.commit()
        conn.close()

        snapshot = get_sync_snapshot(str(repo))

        # Should only have 2 library books
        assert len(snapshot["books"]) == 2
        for book in snapshot["books"]:
            # All books should be from library
            assert book["id"] in [1, 2]
    finally:
        import shutil

        shutil.rmtree(repo)


def test_no_file_modification():
    """Test that sync operations don't modify any files."""
    repo = _make_repo()
    try:
        # Create a test file
        test_file = repo / "library" / "test.txt"
        test_file.write_text("original content", encoding="utf-8")
        original_content = test_file.read_text(encoding="utf-8")

        # Perform sync operations
        get_sync_manifest(str(repo))
        get_sync_snapshot(str(repo))
        sync_upload_progress(
            str(repo),
            "device1",
            [{"book_id": 1, "progress_ratio": 0.5}],
        )

        # Verify file unchanged
        assert test_file.read_text(encoding="utf-8") == original_content
    finally:
        import shutil

        shutil.rmtree(repo)
