from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from novel_manager.server.services.version_replace_service import replace_library_version, restore_replace_library_version
from novel_manager.server.services.operation_service import list_operations, get_operation
from novel_manager.server.services.progress_service import save_progress, get_progress


def _make_repo_for_replace() -> Path:
    """Create a test repo with necessary tables and directories."""
    root = Path(tempfile.mkdtemp(prefix="test_replace_"))
    for d in ["db", "library", "incoming", "archive/replaced", "logs"]:
        (root / d).mkdir(parents=True, exist_ok=True)

    db_path = root / "db" / "novel_repo.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY,
            title_raw TEXT,
            title_norm TEXT,
            file_name TEXT,
            current_path TEXT,
            repo_area TEXT,
            quality_score REAL,
            chapter_count INTEGER,
            char_count_clean INTEGER,
            status TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS reading_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            device_id TEXT NOT NULL DEFAULT 'web',
            progress_ratio REAL NOT NULL DEFAULT 0,
            scroll_position INTEGER NOT NULL DEFAULT 0,
            current_chapter_index INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
            UNIQUE(book_id, device_id)
        );
        CREATE TABLE IF NOT EXISTS web_operation_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT UNIQUE,
            operation_type TEXT NOT NULL,
            book_id INTEGER,
            title TEXT,
            file_name TEXT,
            source_path TEXT,
            target_path TEXT,
            source_area TEXT,
            target_area TEXT,
            status TEXT DEFAULT 'success',
            reversible INTEGER DEFAULT 0,
            restored INTEGER DEFAULT 0,
            restore_operation_id TEXT,
            created_at TEXT,
            detail_json TEXT
        );
    """)
    conn.commit()
    conn.close()
    return root


def _make_book(repo: Path, area: str, name: str, book_id: int, title: str = "Test Book", quality: float = 80.0) -> Path:
    """Create a test book file and insert into database."""
    area_dir = repo / area
    area_dir.mkdir(parents=True, exist_ok=True)
    book_path = area_dir / name
    book_path.write_text(f"Content of {title}\n\nChapter 1\n\nMore content here.", encoding="utf-8")

    db_path = repo / "db" / "novel_repo.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO books (id, title_raw, title_norm, file_name, current_path, repo_area, quality_score, chapter_count, char_count_clean, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'normal', '2024-01-01 00:00:00', '2024-01-01 00:00:00')""",
        (book_id, title, title, name, str(book_path), area, quality, 100, 10000),
    )
    conn.commit()
    conn.close()
    return book_path


class TestReplaceLibraryVersion:
    """Tests for replace_library_version functionality."""

    def test_replace_success(self) -> None:
        """Test successful replacement of library version."""
        repo = _make_repo_for_replace()

        old_book = _make_book(repo, "library", "old_book.txt", 1, "Old Book", 70.0)
        new_book = _make_book(repo, "incoming", "new_book.txt", 2, "New Book", 85.0)

        result = replace_library_version(str(repo), 2, 1)

        assert result["ok"] is True
        assert result["action"] == "replace_library_version"
        assert "old_book_archived_path" in result
        assert "new_book_library_path" in result
        assert "archive" in result["old_book_archived_path"]
        assert "library" in result["new_book_library_path"]

        assert not old_book.exists()
        assert not new_book.exists()

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        old_row = conn.execute("SELECT repo_area, status FROM books WHERE id = 1").fetchone()
        new_row = conn.execute("SELECT repo_area, status FROM books WHERE id = 2").fetchone()
        assert old_row[0] == "archive"
        assert old_row[1] == "replaced_old"
        assert new_row[0] == "library"
        assert new_row[1] == "normal"
        conn.close()

    def test_replace_rejects_non_incoming(self) -> None:
        """Test that replacement rejects non-incoming books."""
        repo = _make_repo_for_replace()

        book1 = _make_book(repo, "library", "book1.txt", 1, "Book 1")
        book2 = _make_book(repo, "library", "book2.txt", 2, "Book 2")

        result = replace_library_version(str(repo), 2, 1)

        assert result["ok"] is False
        assert "新下载区" in result["error"]

    def test_replace_rejects_non_library_matched(self) -> None:
        """Test that replacement rejects non-library matched books."""
        repo = _make_repo_for_replace()

        incoming_book = _make_book(repo, "incoming", "new.txt", 1, "New")
        archive_book = _make_book(repo, "archive", "old.txt", 2, "Old")

        result = replace_library_version(str(repo), 1, 2)

        assert result["ok"] is False
        assert "书架" in result["error"]

    def test_replace_rejects_missing_file(self) -> None:
        """Test that replacement rejects when file is missing."""
        repo = _make_repo_for_replace()

        old_book = _make_book(repo, "library", "old.txt", 1, "Old")

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO books (id, title_raw, file_name, current_path, repo_area, quality_score, chapter_count, char_count_clean, status, created_at, updated_at) VALUES (2, 'New', 'new.txt', ?, 'incoming', 80, 100, 10000, 'normal', '2024-01-01', '2024-01-01')",
            (str(repo / "incoming" / "nonexistent.txt"),),
        )
        conn.commit()
        conn.close()

        result = replace_library_version(str(repo), 2, 1)

        assert result["ok"] is False
        assert "不存在" in result["error"]

    def test_replace_writes_operation_record(self) -> None:
        """Test that replacement writes operation record."""
        repo = _make_repo_for_replace()

        old_book = _make_book(repo, "library", "old.txt", 1, "Old")
        new_book = _make_book(repo, "incoming", "new.txt", 2, "New")

        result = replace_library_version(str(repo), 2, 1)

        assert result["ok"] is True

        ops = list_operations(str(repo))
        assert ops["total"] >= 1

        found = False
        for op in ops["items"]:
            if op["operation_type"] == "replace_library_version":
                found = True
                assert op["reversible"] is True
                assert op["restored"] is False
        assert found

    def test_replace_same_name_conflict(self) -> None:
        """Test that replacement handles same name conflicts."""
        repo = _make_repo_for_replace()

        existing_archive = repo / "archive" / "replaced" / "book.txt"
        existing_archive.parent.mkdir(parents=True, exist_ok=True)
        existing_archive.write_text("existing archive", encoding="utf-8")

        existing_library = repo / "library" / "book.txt"
        existing_library.write_text("existing library", encoding="utf-8")

        old_book = repo / "library" / "book.txt"
        new_book = _make_book(repo, "incoming", "book.txt", 2, "Book")

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO books (id, title_raw, title_norm, file_name, current_path, repo_area, quality_score, chapter_count, char_count_clean, status, created_at, updated_at) VALUES (1, 'Book', 'Book', 'book.txt', ?, 'library', 70, 100, 10000, 'normal', '2024-01-01', '2024-01-01')",
            (str(old_book),),
        )
        conn.commit()
        conn.close()

        result = replace_library_version(str(repo), 2, 1)

        assert result["ok"] is True
        assert existing_archive.exists()
        assert result["old_book_archived_path"] != str(existing_archive)
        assert result["new_book_library_path"] != str(existing_library)


class TestRestoreReplaceLibraryVersion:
    """Tests for restore_replace_library_version functionality."""

    def test_restore_success(self) -> None:
        """Test successful restore of replacement."""
        repo = _make_repo_for_replace()

        old_book = _make_book(repo, "library", "old.txt", 1, "Old")
        new_book = _make_book(repo, "incoming", "new.txt", 2, "New")

        replace_result = replace_library_version(str(repo), 2, 1)
        assert replace_result["ok"] is True

        ops = list_operations(str(repo))
        op_id = None
        for op in ops["items"]:
            if op["operation_type"] == "replace_library_version" and not op["restored"]:
                op_id = op["operation_id"]
                break

        assert op_id is not None

        restore_result = restore_replace_library_version(str(repo), op_id)
        assert restore_result["ok"] is True

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        old_row = conn.execute("SELECT repo_area FROM books WHERE id = 1").fetchone()
        new_row = conn.execute("SELECT repo_area FROM books WHERE id = 2").fetchone()
        assert old_row[0] == "library"
        assert new_row[0] == "incoming"
        conn.close()

        op = get_operation(str(repo), op_id)
        assert op["restored"] is True

    def test_restore_rejects_twice(self) -> None:
        """Test that restore rejects already restored operations."""
        repo = _make_repo_for_replace()

        old_book = _make_book(repo, "library", "old.txt", 1, "Old")
        new_book = _make_book(repo, "incoming", "new.txt", 2, "New")

        replace_result = replace_library_version(str(repo), 2, 1)
        assert replace_result["ok"] is True

        ops = list_operations(str(repo))
        op_id = None
        for op in ops["items"]:
            if op["operation_type"] == "replace_library_version" and not op["restored"]:
                op_id = op["operation_id"]
                break

        restore_result = restore_replace_library_version(str(repo), op_id)
        assert restore_result["ok"] is True

        second_restore = restore_replace_library_version(str(repo), op_id)
        assert second_restore["ok"] is False
        assert "已经恢复过" in second_restore["error"]

    def test_restore_rejects_missing_detail(self) -> None:
        """Test that restore rejects when detail_json is missing."""
        repo = _make_repo_for_replace()

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO web_operation_records (operation_id, operation_type, book_id, title, reversible, restored, created_at) VALUES (?, 'replace_library_version', 1, 'Test', 1, 0, '2024-01-01')",
            ("test-op-123",),
        )
        conn.commit()
        conn.close()

        result = restore_replace_library_version(str(repo), "test-op-123")
        assert result["ok"] is False
        assert "详情" in result["error"]


class TestNoPermanentDelete:
    """Ensure no permanent delete operations."""

    def test_replace_does_not_delete(self) -> None:
        """Verify replace doesn't call os.remove or shutil.rmtree."""
        import novel_manager.server.services.version_replace_service as vrs

        source = vrs.__file__
        content = Path(source).read_text(encoding="utf-8")

        assert "os.remove" not in content
        assert "shutil.rmtree" not in content
        assert ".unlink(" not in content


class TestProgressInheritance:
    """Tests for reading progress inheritance during version replacement."""

    def test_replace_copies_old_progress_to_new(self) -> None:
        """Replace copies old book's reading progress to new book."""
        repo = _make_repo_for_replace()
        old_book = _make_book(repo, "library", "old.txt", 1, "Old")
        new_book = _make_book(repo, "incoming", "new.txt", 2, "New")

        save_progress(str(repo), 1, 0.65, 320, "web", 5)

        result = replace_library_version(str(repo), 2, 1)
        assert result["ok"] is True
        assert result["progress_transfer"]["copied"] == 1
        assert result["progress_transfer"]["skipped"] == 0
        assert "web" in result["progress_transfer"]["devices"]

        new_progress = get_progress(str(repo), 2, "web")
        assert new_progress is not None
        assert abs(new_progress["progress_ratio"] - 0.65) < 0.01
        assert new_progress["scroll_position"] == 320
        assert new_progress["current_chapter_index"] == 5

    def test_replace_copies_multiple_devices(self) -> None:
        """Replace copies progress from all devices."""
        repo = _make_repo_for_replace()
        old_book = _make_book(repo, "library", "old.txt", 1, "Old")
        new_book = _make_book(repo, "incoming", "new.txt", 2, "New")

        save_progress(str(repo), 1, 0.5, 100, "web", 3)
        save_progress(str(repo), 1, 0.7, 200, "phone", 7)
        save_progress(str(repo), 1, 0.3, 50, "tablet", 2)

        result = replace_library_version(str(repo), 2, 1)
        assert result["ok"] is True
        assert result["progress_transfer"]["copied"] == 3
        assert sorted(result["progress_transfer"]["devices"]) == ["phone", "tablet", "web"]

        for device, ratio, pos, ch in [("web", 0.5, 100, 3), ("phone", 0.7, 200, 7), ("tablet", 0.3, 50, 2)]:
            p = get_progress(str(repo), 2, device)
            assert p is not None
            assert abs(p["progress_ratio"] - ratio) < 0.01
            assert p["scroll_position"] == pos
            assert p["current_chapter_index"] == ch

    def test_replace_keeps_newer_progress_on_conflict(self) -> None:
        """When new book already has progress for a device, keep the newer one."""
        repo = _make_repo_for_replace()
        old_book = _make_book(repo, "library", "old.txt", 1, "Old")
        new_book = _make_book(repo, "incoming", "new.txt", 2, "New")

        # Old book has older progress
        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO reading_progress (book_id, device_id, progress_ratio, scroll_position, current_chapter_index, updated_at) VALUES (1, 'web', 0.4, 100, 3, '2024-01-01 10:00:00')",
        )
        # New book already has newer progress
        conn.execute(
            "INSERT INTO reading_progress (book_id, device_id, progress_ratio, scroll_position, current_chapter_index, updated_at) VALUES (2, 'web', 0.8, 500, 10, '2024-06-01 10:00:00')",
        )
        conn.commit()
        conn.close()

        result = replace_library_version(str(repo), 2, 1)
        assert result["ok"] is True
        assert result["progress_transfer"]["skipped"] == 1

        # New book's progress should remain unchanged
        p = get_progress(str(repo), 2, "web")
        assert p is not None
        assert abs(p["progress_ratio"] - 0.8) < 0.01

    def test_replace_overwrites_when_old_is_newer(self) -> None:
        """When old book has newer progress than new book, overwrite with old."""
        repo = _make_repo_for_replace()
        old_book = _make_book(repo, "library", "old.txt", 1, "Old")
        new_book = _make_book(repo, "incoming", "new.txt", 2, "New")

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        # Old book has newer progress
        conn.execute(
            "INSERT INTO reading_progress (book_id, device_id, progress_ratio, scroll_position, current_chapter_index, updated_at) VALUES (1, 'web', 0.9, 800, 15, '2024-06-01 10:00:00')",
        )
        # New book has older progress
        conn.execute(
            "INSERT INTO reading_progress (book_id, device_id, progress_ratio, scroll_position, current_chapter_index, updated_at) VALUES (2, 'web', 0.2, 50, 1, '2024-01-01 10:00:00')",
        )
        conn.commit()
        conn.close()

        result = replace_library_version(str(repo), 2, 1)
        assert result["ok"] is True
        assert result["progress_transfer"]["copied"] == 1

        p = get_progress(str(repo), 2, "web")
        assert p is not None
        assert abs(p["progress_ratio"] - 0.9) < 0.01
        assert p["scroll_position"] == 800

    def test_replace_detail_json_contains_progress_transfer(self) -> None:
        """Operation record detail_json includes progress_transfer."""
        repo = _make_repo_for_replace()
        old_book = _make_book(repo, "library", "old.txt", 1, "Old")
        new_book = _make_book(repo, "incoming", "new.txt", 2, "New")

        save_progress(str(repo), 1, 0.55, 250, "web", 4)

        result = replace_library_version(str(repo), 2, 1)
        assert result["ok"] is True

        import json
        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT detail_json FROM web_operation_records WHERE operation_type = 'replace_library_version'",
        ).fetchone()
        conn.close()
        assert row is not None

        detail = json.loads(row[0])
        assert "progress_transfer" in detail
        assert detail["progress_transfer"]["from_book_id"] == 1
        assert detail["progress_transfer"]["to_book_id"] == 2
        assert detail["progress_transfer"]["copied"] == 1

    def test_replace_no_old_progress_works(self) -> None:
        """Replace works normally when old book has no reading progress."""
        repo = _make_repo_for_replace()
        old_book = _make_book(repo, "library", "old.txt", 1, "Old")
        new_book = _make_book(repo, "incoming", "new.txt", 2, "New")

        result = replace_library_version(str(repo), 2, 1)
        assert result["ok"] is True
        assert result["progress_transfer"]["copied"] == 0
        assert result["progress_transfer"]["skipped"] == 0
        assert result["progress_transfer"]["devices"] == []

    def test_restore_preserves_progress(self) -> None:
        """Restore doesn't delete reading progress from either book."""
        repo = _make_repo_for_replace()
        old_book = _make_book(repo, "library", "old.txt", 1, "Old")
        new_book = _make_book(repo, "incoming", "new.txt", 2, "New")

        save_progress(str(repo), 1, 0.6, 300, "web", 5)

        replace_result = replace_library_version(str(repo), 2, 1)
        assert replace_result["ok"] is True

        # After replace, new book (now in library) should have progress
        p = get_progress(str(repo), 2, "web")
        assert p is not None

        ops = list_operations(str(repo))
        op_id = None
        for op in ops["items"]:
            if op["operation_type"] == "replace_library_version" and not op["restored"]:
                op_id = op["operation_id"]
                break
        assert op_id is not None

        restore_result = restore_replace_library_version(str(repo), op_id)
        assert restore_result["ok"] is True

        # After restore, both books' progress should still exist
        old_p = get_progress(str(repo), 1, "web")
        new_p = get_progress(str(repo), 2, "web")
        assert old_p is not None
        assert new_p is not None
