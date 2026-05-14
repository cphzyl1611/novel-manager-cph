from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from novel_manager.server.services.health_service import get_health_summary, list_health_issues


def _make_test_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="test_health_"))
    for d in ["db", "library", "incoming", "review_duplicates", "archive/replaced", "trash", "logs", "reports/incoming"]:
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
            raw_sha256 TEXT,
            status TEXT,
            created_at TEXT,
            updated_at TEXT
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
            created_at TEXT,
            detail_json TEXT
        );
        CREATE TABLE IF NOT EXISTS update_candidates (
            id INTEGER PRIMARY KEY,
            old_book_id INTEGER,
            new_book_id INTEGER,
            same_work_score REAL,
            coverage_score REAL,
            new_content_score REAL,
            quality_delta REAL,
            old_chapter_count INTEGER,
            new_chapter_count INTEGER,
            recommendation TEXT,
            reason_summary TEXT,
            risk_flags TEXT
        );
    """)
    conn.commit()
    conn.close()

    (root / "logs" / "operations.log").write_text("", encoding="utf-8")
    return root


def _insert_book(repo: Path, area: str, name: str, book_id: int, title: str = "Test Book", raw_sha256: str = None) -> Path:
    area_dir = repo / area
    area_dir.mkdir(parents=True, exist_ok=True)
    book_path = area_dir / name
    book_path.write_text(f"Content of {title}\n\nChapter 1\n\nMore content.", encoding="utf-8")

    db_path = repo / "db" / "novel_repo.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO books (id, title_raw, title_norm, file_name, current_path, repo_area, quality_score, chapter_count, char_count_clean, raw_sha256, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'normal', '2024-01-01', '2024-01-01')",
        (book_id, title, title, name, str(book_path), area, 80.0, 100, 10000, raw_sha256 or ""),
    )
    conn.commit()
    conn.close()
    return book_path


class TestHealthSummary:
    def test_summary_ok_on_empty_repo(self) -> None:
        repo = _make_test_repo()
        result = get_health_summary(str(repo))

        assert result["status"] == "ok"
        assert result["books"]["total"] == 0
        assert result["books"]["library"] == 0
        assert result["books"]["incoming"] == 0
        assert result["books"]["review_duplicates"] == 0
        assert result["books"]["archive"] == 0
        assert result["integrity"]["missing_files"] == 0
        assert result["integrity"]["path_area_mismatch"] == 0
        assert result["warnings"] == []

    def test_summary_counts_books_by_area(self) -> None:
        repo = _make_test_repo()
        _insert_book(repo, "library", "lib.txt", 1, "Library Book")
        _insert_book(repo, "library", "lib2.txt", 2, "Library Book 2")
        _insert_book(repo, "incoming", "inc.txt", 3, "Incoming Book")
        _insert_book(repo, "review_duplicates", "rev.txt", 4, "Review Book")

        result = get_health_summary(str(repo))

        assert result["books"]["total"] == 4
        assert result["books"]["library"] == 2
        assert result["books"]["incoming"] == 1
        assert result["books"]["review_duplicates"] == 1

    def test_summary_detects_missing_file(self) -> None:
        repo = _make_test_repo()

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO books (id, title_raw, file_name, current_path, repo_area, quality_score, chapter_count, char_count_clean, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'normal', '2024-01-01', '2024-01-01')",
            (1, "Missing", "missing.txt", str(repo / "library" / "missing.txt"), "library", 80.0, 100, 10000),
        )
        conn.commit()
        conn.close()

        result = get_health_summary(str(repo))
        assert result["integrity"]["missing_files"] == 1
        assert result["status"] == "warning"

    def test_summary_detects_path_area_mismatch(self) -> None:
        repo = _make_test_repo()
        _insert_book(repo, "incoming", "mismatch.txt", 1, "Mismatch")

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE books SET repo_area = 'library' WHERE id = 1")
        conn.commit()
        conn.close()

        result = get_health_summary(str(repo))
        assert result["integrity"]["path_area_mismatch"] == 1
        assert result["status"] == "warning"

    def test_summary_detects_stale_incoming(self) -> None:
        repo = _make_test_repo()

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO books (id, title_raw, file_name, current_path, repo_area, quality_score, chapter_count, char_count_clean, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'normal', '2024-01-01', '2024-01-01')",
            (1, "Stale", "stale.txt", str(repo / "library" / "stale.txt"), "incoming", 80.0, 100, 10000),
        )
        conn.commit()
        conn.close()

        result = get_health_summary(str(repo))
        assert result["integrity"]["stale_incoming_records"] >= 1

    def test_summary_ok_when_no_issues(self) -> None:
        repo = _make_test_repo()
        _insert_book(repo, "library", "book.txt", 1, "Book")
        result = get_health_summary(str(repo))

        assert result["status"] == "ok"
        assert result["integrity"]["missing_files"] == 0
        assert result["integrity"]["path_area_mismatch"] == 0

    def test_summary_warning_on_issue(self) -> None:
        repo = _make_test_repo()

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO books (id, title_raw, file_name, current_path, repo_area, quality_score, chapter_count, char_count_clean, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'normal', '2024-01-01', '2024-01-01')",
            (1, "Missing", "missing.txt", str(repo / "library" / "missing.txt"), "library", 80.0, 100, 10000),
        )
        conn.commit()
        conn.close()

        result = get_health_summary(str(repo))
        assert result["status"] == "warning"
        assert len(result["warnings"]) >= 1


class TestHealthIssues:
    def test_issues_empty_on_clean_repo(self) -> None:
        repo = _make_test_repo()
        result = list_health_issues(str(repo))
        assert result["items"] == []

    def test_issues_detects_missing_file(self) -> None:
        repo = _make_test_repo()

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO books (id, title_raw, file_name, current_path, repo_area, quality_score, chapter_count, char_count_clean, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'normal', '2024-01-01', '2024-01-01')",
            (1, "Missing Book", "missing.txt", str(repo / "library" / "missing.txt"), "library", 80.0, 100, 10000),
        )
        conn.commit()
        conn.close()

        result = list_health_issues(str(repo))

        missing = [i for i in result["items"] if i["code"] == "missing_file"]
        assert len(missing) >= 1
        assert missing[0]["severity"] == "error"
        assert missing[0]["book_id"] == 1

    def test_issues_detects_path_area_mismatch(self) -> None:
        repo = _make_test_repo()
        _insert_book(repo, "incoming", "mismatch.txt", 1, "Mismatch")

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE books SET repo_area = 'library' WHERE id = 1")
        conn.commit()
        conn.close()

        result = list_health_issues(str(repo))

        mismatch = [i for i in result["items"] if i["code"] == "path_area_mismatch"]
        assert len(mismatch) >= 1
        assert mismatch[0]["severity"] == "warning"

    def test_issues_detects_stale_incoming(self) -> None:
        repo = _make_test_repo()

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO books (id, title_raw, file_name, current_path, repo_area, quality_score, chapter_count, char_count_clean, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'normal', '2024-01-01', '2024-01-01')",
            (1, "Stale", "stale.txt", str(repo / "library" / "stale.txt"), "incoming", 80.0, 100, 10000),
        )
        conn.commit()
        conn.close()

        result = list_health_issues(str(repo))
        stale = [i for i in result["items"] if i["code"] == "stale_incoming_record"]
        assert len(stale) >= 1

    def test_issues_detects_restore_target_missing(self) -> None:
        repo = _make_test_repo()

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO web_operation_records (operation_id, operation_type, book_id, title, file_name, target_path, source_area, target_area, reversible, restored, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 'success', '2024-01-01')",
            ("test-op-1", "import_to_library", 1, "Test", "test.txt", str(repo / "library" / "missing.txt"), "incoming", "library"),
        )
        conn.commit()
        conn.close()

        result = list_health_issues(str(repo))

        restore = [i for i in result["items"] if i["code"] == "restore_target_missing"]
        assert len(restore) >= 1
        assert restore[0]["severity"] == "warning"


class TestNoFileModification:
    def test_health_does_not_modify_files(self) -> None:
        repo = _make_test_repo()
        book = _insert_book(repo, "library", "book.txt", 1, "Book")
        original = book.read_text(encoding="utf-8")

        get_health_summary(str(repo))
        list_health_issues(str(repo))

        assert book.exists()
        assert book.read_text(encoding="utf-8") == original

    def test_health_does_not_delete(self) -> None:
        import novel_manager.server.services.health_service as hs

        source = Path(hs.__file__)
        content = source.read_text(encoding="utf-8")

        assert "os.remove" not in content
        assert "shutil.rmtree" not in content
        assert ".unlink(" not in content
        assert "shutil.move" not in content
