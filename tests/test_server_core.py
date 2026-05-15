from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from novel_manager.server.config import is_safe_path
from novel_manager.server.services.book_service import get_book_content, get_book_detail, list_books
from novel_manager.server.services.group_service import create_group, list_groups
from novel_manager.server.services.issue_service import get_issues
from novel_manager.server.services.repo_service import get_repo_status
from novel_manager.server.services.sync_service import get_sync_status
from novel_manager.server.services.upload_service import analyze_incoming, sanitize_filename, is_allowed_file, save_upload, scan_incoming, safe_incoming_path
from novel_manager.server.services.incoming_service import compare_books, import_to_library, move_to_review_duplicates
from novel_manager.server.services.operation_service import get_operation, list_operations, record_operation, restore_operation
from novel_manager.server.services.task_service import get_updates_summary


def _make_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="test_novel_repo_"))
    for d in ["db", "config", "library", "incoming", "reports/duplicate", "reports/update", "reports/rename", "logs"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "config" / "config.yaml").write_text("repo_version: 1\n", encoding="utf-8")
    db_path = root / "db" / "novel_repo.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY, current_path TEXT, file_name TEXT,
            repo_area TEXT, title_raw TEXT, title_norm TEXT, author_norm TEXT,
            author_raw TEXT, raw_sha256 TEXT, clean_sha256 TEXT,
            quality_score REAL, quality_level TEXT, chapter_count INTEGER,
            char_count_clean INTEGER, file_size INTEGER, encoding TEXT,
            reading_status TEXT, updated_at TEXT, status TEXT,
            char_count_raw INTEGER, line_count_raw INTEGER, line_count_clean INTEGER,
            mojibake_rate REAL, ad_line_count INTEGER, ad_line_rate REAL,
            duplicate_chapter_count INTEGER, missing_chapter_count INTEGER,
            chapter_order_error_count INTEGER, truncated_risk INTEGER
        );
        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY, book_id INTEGER, chapter_index INTEGER,
            chapter_no INTEGER, chapter_type TEXT, title_raw TEXT, title_norm TEXT,
            start_offset INTEGER, end_offset INTEGER, char_count INTEGER
        );
        CREATE TABLE IF NOT EXISTS tags (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE IF NOT EXISTS book_tags (book_id INTEGER, tag_id INTEGER);
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY, operation_type TEXT, book_id INTEGER,
            source_path TEXT, target_path TEXT, status TEXT, summary TEXT, applied_at TEXT
        );
    """)
    conn.executemany(
        "INSERT INTO books (id, current_path, file_name, repo_area, title_raw, title_norm, author_norm, quality_score, quality_level, chapter_count, char_count_clean, file_size, encoding, reading_status, updated_at, author_raw, raw_sha256, clean_sha256, status, char_count_raw, line_count_raw, line_count_clean, mojibake_rate, ad_line_count, ad_line_rate, duplicate_chapter_count, missing_chapter_count, chapter_order_error_count, truncated_risk) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL)",
        [
            (1, str(root / "library" / "a.txt"), "a.txt", "library", "测试A", "测试A", "作者A", 85.0, "good", 50, 50000, 1024, "utf-8", None, "2026-01-01"),
            (2, str(root / "library" / "b.txt"), "b.txt", "library", "测试B", "测试B", "作者B", 60.0, "fair", 30, 30000, 2048, "utf-8", "正在读", "2026-01-02"),
            (3, str(root / "incoming" / "c.txt"), "c.txt", "incoming", "新书C", "新书C", "作者C", None, None, 20, 20000, 512, "gbk", None, "2026-01-03"),
        ],
    )
    conn.commit(); conn.close()
    (root / "library" / "a.txt").write_text("第一章\n内容\n第二章\n更多", encoding="utf-8")
    (root / "library" / "b.txt").write_text("第一章 开始\n正文", encoding="utf-8")
    (root / "incoming" / "c.txt").write_text("新书内容", encoding="utf-8")
    (root / "logs" / "operations.log").write_text("[2026-01-01 12:00:00] scan\n[2026-01-02 14:00:00] rename\n", encoding="utf-8")
    return root


class TestRepoStatus:
    def test_nonexistent(self):
        r = get_repo_status("/nonexistent/path/xyz")
        assert r["initialized"] is False

    def test_existing(self):
        repo = _make_repo()
        r = get_repo_status(str(repo))
        assert r["initialized"] is True
        assert r["book_count"] == 3
        assert r["library_count"] == 2


class TestBooksService:
    def test_list_all(self):
        repo = _make_repo()
        r = list_books(str(repo), limit=10)
        # Only 2 library books with existing files pass path validation
        assert r["total"] == 2

    def test_search(self):
        repo = _make_repo()
        r = list_books(str(repo), q="作者A")
        assert r["total"] == 1

    def test_area_filter(self):
        repo = _make_repo()
        r = list_books(str(repo), area="incoming")
        assert r["total"] == 1

    def test_pagination(self):
        repo = _make_repo()
        p1 = list_books(str(repo), limit=1, offset=0)
        p2 = list_books(str(repo), limit=1, offset=1)
        assert len(p1["items"]) == 1
        assert p1["items"][0]["book_id"] != p2["items"][0]["book_id"]

    def test_no_crash_on_missing_fields(self):
        repo = _make_repo()
        r = list_books(str(repo))
        for item in r["items"]:
            assert "book_id" in item

    def test_detail(self):
        repo = _make_repo()
        d = get_book_detail(str(repo), 1)
        assert d is not None
        assert d["title"] == "测试A"

    def test_detail_nonexistent(self):
        repo = _make_repo()
        assert get_book_detail(str(repo), 999) is None


class TestPathSafety:
    def test_safe_path(self):
        p = Path("/tmp/repo")
        assert is_safe_path(p, Path("/tmp/repo/library/a.txt")) is True
        assert is_safe_path(p, Path("/etc/passwd")) is False
        assert is_safe_path(p, Path("/tmp/repo/../../etc/passwd")) is False

    def test_content_reads_repo_file(self):
        repo = _make_repo()
        r = get_book_content(str(repo), 1)
        assert r is not None
        assert "内容" in r["content"]

    def test_group_sanitizes_path_traversal(self):
        repo = _make_repo()
        r = create_group(str(repo), "../evil")
        assert r.get("ok") is True
        assert r.get("name") == "evil"

    def test_group_sanitizes_chars(self):
        repo = _make_repo()
        r = create_group(str(repo), "test:group*?")
        assert r.get("ok") is True
        assert ":" not in r.get("name", "")


class TestGroups:
    def test_default_group(self):
        repo = _make_repo()
        r = list_groups(str(repo))
        assert any(g["name"] == "默认分组" for g in r["items"])

    def test_create_folder(self):
        repo = _make_repo()
        r = create_group(str(repo), "玄幻")
        assert r["ok"] is True
        assert (Path(repo) / "library" / "玄幻").exists()

    def test_create_existing(self):
        repo = _make_repo()
        create_group(str(repo), "武侠")
        r = create_group(str(repo), "武侠")
        assert r["ok"] is True
        assert r.get("existed") is True

    def test_invalid_name(self):
        repo = _make_repo()
        r = create_group(str(repo), "")
        assert r.get("ok") is False


class TestIssues:
    def test_zeros_without_reports(self):
        repo = _make_repo()
        r = get_issues(str(repo))
        assert r["duplicate_count"] == 0

    def test_detects_incoming(self):
        repo = _make_repo()
        r = get_issues(str(repo))
        assert r["incoming_count"] == 1

    def test_with_rename_report(self):
        repo = _make_repo()
        (repo / "reports" / "rename").mkdir(parents=True, exist_ok=True)
        (repo / "reports" / "rename" / "rename_plan_test.json").write_text(
            json.dumps({"suggestions": [{"action": "rename_recommended"}, {"action": "manual_review"}]}),
            encoding="utf-8")
        r = get_issues(str(repo))
        assert r["rename_recommended"] == 1


class TestSync:
    def test_counts_ops(self):
        repo = _make_repo()
        r = get_sync_status(str(repo))
        # server_revision starts at 0, repo_id and device_id are generated
        assert r["repo_revision"] >= 0
        assert "server_device_id" in r
        assert "repo_id" in r


class TestUpdates:
    def test_no_reports(self):
        repo = _make_repo()
        r = get_updates_summary(str(repo))
        assert r["replace_recommended"] == 0

    def test_with_report(self):
        repo = _make_repo()
        (repo / "reports" / "update").mkdir(parents=True, exist_ok=True)
        (repo / "reports" / "update" / "update_report_test.json").write_text(
            json.dumps({"candidates": [
                {"recommendation": "replace_recommended", "old_file": "a.txt", "new_file": "b.txt"},
                {"recommendation": "review"}, {"recommendation": "reject"}
            ]}), encoding="utf-8")
        r = get_updates_summary(str(repo))
        assert r["replace_recommended"] == 1
        assert r["manual_review"] == 1
        assert r["reject"] == 1


TEST_TEXT = "中文测试：高考陪读那三年\n第二章 新的开始\n内容包含常见汉字和标点。"


def _write_test_txt(path: Path, text: str, encoding: str) -> None:
    path.write_text(text, encoding=encoding)


class TestTextReader:
    def test_utf8(self):
        p = Path(tempfile.mktemp(suffix=".txt"))
        _write_test_txt(p, TEST_TEXT, "utf-8")
        from novel_manager.server.services.text_reader import read_text_safely
        r = read_text_safely(p)
        assert "高考陪读那三年" in r["text"]
        assert r["encoding"] in ("utf-8", "utf_8")
        assert r["decode_warning"] is None or r["replacement_ratio"] < 0.01

    def test_utf8_sig(self):
        p = Path(tempfile.mktemp(suffix=".txt"))
        _write_test_txt(p, TEST_TEXT, "utf-8-sig")
        from novel_manager.server.services.text_reader import read_text_safely
        r = read_text_safely(p)
        assert "高考陪读那三年" in r["text"]
        assert r["encoding"] in ("utf-8-sig", "utf_8_sig")

    def test_gbk(self):
        p = Path(tempfile.mktemp(suffix=".txt"))
        _write_test_txt(p, TEST_TEXT, "gbk")
        from novel_manager.server.services.text_reader import read_text_safely
        r = read_text_safely(p)
        assert "高考陪读那三年" in r["text"]

    def test_gb18030(self):
        p = Path(tempfile.mktemp(suffix=".txt"))
        _write_test_txt(p, TEST_TEXT, "gb18030")
        from novel_manager.server.services.text_reader import read_text_safely
        r = read_text_safely(p)
        assert "高考陪读那三年" in r["text"]

    def test_utf16_le(self):
        p = Path(tempfile.mktemp(suffix=".txt"))
        _write_test_txt(p, TEST_TEXT, "utf-16-le")
        from novel_manager.server.services.text_reader import read_text_safely
        r = read_text_safely(p)
        assert "高考陪读那三年" in r["text"]

    def test_utf16_be(self):
        p = Path(tempfile.mktemp(suffix=".txt"))
        _write_test_txt(p, TEST_TEXT, "utf-16-be")
        from novel_manager.server.services.text_reader import read_text_safely
        r = read_text_safely(p)
        assert "高考陪读那三年" in r["text"]

    def test_returns_encoding_field(self):
        p = Path(tempfile.mktemp(suffix=".txt"))
        _write_test_txt(p, TEST_TEXT, "gbk")
        from novel_manager.server.services.text_reader import read_text_safely
        r = read_text_safely(p)
        assert "encoding" in r
        assert r["encoding"]

    def test_does_not_crash_on_binary(self):
        p = Path(tempfile.mktemp(suffix=".txt"))
        p.write_bytes(bytes(range(256)))
        from novel_manager.server.services.text_reader import read_text_safely
        r = read_text_safely(p)
        assert "text" in r

    def test_max_bytes_respected(self):
        p = Path(tempfile.mktemp(suffix=".txt"))
        _write_test_txt(p, TEST_TEXT * 500, "utf-8")
        from novel_manager.server.services.text_reader import read_text_safely
        r = read_text_safely(p, max_bytes=1000)
        assert r["source_size"] > 1000
        assert len(r["text"]) <= 1000

    def test_content_api_returns_encoding(self):
        repo = _make_repo()
        import sqlite3 as _sql
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        conn.row_factory = _sql.Row
        conn.execute("UPDATE books SET encoding = ? WHERE id = 1", ("gbk",))
        conn.commit(); conn.close()
        (repo / "library" / "a.txt").write_text(TEST_TEXT, encoding="gbk")
        r = get_book_content(str(repo), 1)
        assert r is not None
        assert "encoding" in r

    def test_content_api_rejects_unsafe_path(self):
        repo = _make_repo()
        import sqlite3 as _sql
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        conn.row_factory = _sql.Row
        conn.execute("UPDATE books SET current_path = ? WHERE id = 1", ("/etc/passwd",))
        conn.commit(); conn.close()
        r = get_book_content(str(repo), 1)
        assert "路径不在仓库范围内" in r.get("error", "")

    def test_content_api_missing_file_graceful(self):
        repo = _make_repo()
        import sqlite3 as _sql
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        conn.row_factory = _sql.Row
        conn.execute("UPDATE books SET current_path = ? WHERE id = 1",
                     (str(repo / "library" / "nonexistent.txt"),))
        conn.commit(); conn.close()
        r = get_book_content(str(repo), 1)
        assert r.get("error") == "文件不存在"


class TestReadingProgress:
    def test_save_and_load(self):
        repo = _make_repo()
        from novel_manager.server.services.progress_service import save_progress, get_progress
        save_progress(str(repo), 1, 0.35, 5000)
        p = get_progress(str(repo), 1)
        assert p is not None
        assert p["progress_ratio"] == 0.35
        assert p["scroll_position"] == 5000

    def test_overwrite_progress(self):
        repo = _make_repo()
        from novel_manager.server.services.progress_service import save_progress, get_progress
        save_progress(str(repo), 1, 0.2, 100)
        save_progress(str(repo), 1, 0.8, 9999)
        p = get_progress(str(repo), 1)
        assert p["progress_ratio"] == 0.8
        assert p["scroll_position"] == 9999

    def test_clamp_ratio_below_zero(self):
        repo = _make_repo()
        from novel_manager.server.services.progress_service import save_progress
        r = save_progress(str(repo), 1, -0.5, 0)
        assert r["progress_ratio"] == 0.0

    def test_clamp_ratio_above_one(self):
        repo = _make_repo()
        from novel_manager.server.services.progress_service import save_progress
        r = save_progress(str(repo), 1, 1.5, 0)
        assert r["progress_ratio"] == 1.0

    def test_clamp_negative_scroll(self):
        repo = _make_repo()
        from novel_manager.server.services.progress_service import save_progress
        r = save_progress(str(repo), 1, 0.5, -100)
        assert r["scroll_position"] == 0

    def test_nonexistent_book(self):
        repo = _make_repo()
        from novel_manager.server.services.progress_service import save_progress
        r = save_progress(str(repo), 999, 0.5, 0)
        assert r.get("ok") is False

    def test_table_auto_created(self):
        repo = _make_repo()
        import sqlite3
        db = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        from novel_manager.server.services.progress_service import get_progress
        get_progress(str(repo), 1)
        conn = sqlite3.connect(str(db))
        tables2 = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert "reading_progress" in tables2

    def test_books_api_unaffected(self):
        repo = _make_repo()
        from novel_manager.server.services.progress_service import save_progress
        save_progress(str(repo), 1, 0.5, 100)
        r = list_books(str(repo))
        # Only 2 library books with existing files
        assert r["total"] == 2



class TestUpload:
    def test_sanitize_removes_illegal_chars(self):
        assert ":" not in sanitize_filename("evil:file.txt")
        assert ".." not in sanitize_filename("../escape.txt")

    def test_sanitize_adds_txt_extension(self):
        result = sanitize_filename("noext")
        assert result.endswith(".txt")

    def test_sanitize_empty_returns_generated_name(self):
        result = sanitize_filename("")
        assert result.endswith(".txt")

    def test_is_allowed_rejects_non_txt(self):
        assert is_allowed_file("a.txt") is True
        assert is_allowed_file("a.pdf") is False
        assert is_allowed_file("a.exe") is False

    def test_save_upload_success(self):
        repo = _make_repo()
        r = save_upload(str(repo), "test.txt", b"hello world")
        assert r["status"] == "success"
        assert r["size"] == 11

    def test_save_upload_rejects_non_txt(self):
        repo = _make_repo()
        r = save_upload(str(repo), "test.pdf", b"x")
        assert r["status"] == "skipped"

    def test_save_upload_creates_incoming(self):
        repo = _make_repo()
        import shutil
        incoming = repo / "incoming"
        if incoming.exists():
            shutil.rmtree(incoming)
        r = save_upload(str(repo), "test.txt", b"x")
        assert r["status"] == "success"
        assert incoming.exists()

    def test_save_upload_renames_on_collision(self):
        repo = _make_repo()
        r1 = save_upload(str(repo), "dup.txt", b"a")
        r2 = save_upload(str(repo), "dup.txt", b"b")
        assert r1["status"] == "success"
        assert r2["status"] == "success"
        assert r1["saved_name"] != r2["saved_name"]

    def test_save_upload_to_incoming_not_library(self):
        repo = _make_repo()
        r = save_upload(str(repo), "test.txt", b"x")
        assert "incoming" in r["path"]
        assert "library" not in r["path"]

    def test_scan_incoming_works(self):
        repo = _make_repo()
        save_upload(str(repo), "scan1.txt", b"hello")
        r = scan_incoming(str(repo))
        assert r["found"] >= 1
        repo = _make_repo()
    def test_analyze_incoming_does_not_move_files(self):
        repo = _make_repo()
        save_upload(str(repo), "an_test.txt", b"test content")
        scan_incoming(str(repo))
        incoming = repo / "incoming"
        before = set(p.name for p in incoming.glob("*.txt") if p.is_file())
        analyze_incoming(str(repo))
        after = set(p.name for p in incoming.glob("*.txt") if p.is_file())
        assert before == after

    def test_analyze_incoming_returns_summary(self):
        repo = _make_repo()
        save_upload(str(repo), "an_test2.txt", b"unique content for analysis")
        scan_incoming(str(repo))
        r = analyze_incoming(str(repo))
        assert "summary" in r
        assert "items" in r

    def test_analyze_incoming_saves_json_report(self):
        repo = _make_repo()
        save_upload(str(repo), "an_test3.txt", b"report test content")
        scan_incoming(str(repo))
        analyze_incoming(str(repo))
        reports = list((repo / "reports" / "incoming").glob("incoming_analysis_*.json"))
        assert len(reports) >= 1

    def test_analyze_incoming_empty_when_no_incoming(self):
        repo = _make_repo()
        import sqlite3 as _sql
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        conn.execute("DELETE FROM books WHERE repo_area = 'incoming'")
        conn.commit(); conn.close()
        r = analyze_incoming(str(repo))
        assert r["summary"]["incoming_count"] == 0

    def test_analyze_incoming_no_crash_on_invalid(self):
        r = analyze_incoming("/nonexistent/path/xyz")
        assert "summary" in r


class TestOperationRecords:
    def test_table_auto_created(self):
        repo = _make_repo()
        import sqlite3 as _sql
        record_operation(str(repo), "import_to_library", 1, "测试", "test.txt", "/src/a.txt", "/dst/a.txt", "incoming", "library", reversible=True)
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert "web_operation_records" in tables

    def test_record_written(self):
        repo = _make_repo()
        op_id = record_operation(str(repo), "import_to_library", 1, "测试", "test.txt", "/src/a.txt", "/dst/a.txt", "incoming", "library", reversible=True)
        assert op_id
        r = get_operation(str(repo), op_id)
        assert r is not None
        assert r["operation_type"] == "import_to_library"
        assert r["reversible"] is True

    def test_list_operations(self):
        repo = _make_repo()
        record_operation(str(repo), "import_to_library", 1, "A", "a.txt", "/s/a.txt", "/t/a.txt", "incoming", "library", reversible=True)
        record_operation(str(repo), "move_to_review_duplicates", 2, "B", "b.txt", "/s/b.txt", "/t/b.txt", "incoming", "review_duplicates", reversible=True)
        r = list_operations(str(repo))
        assert r["total"] >= 2

    def test_restore_import_to_library(self):
        repo = _make_repo()
        save_upload(str(repo), "restore_test.txt", b"restore")
        from novel_manager.server.services.upload_service import scan_incoming
        scan_incoming(str(repo))
        import sqlite3 as _sql
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        row = conn.execute("SELECT id FROM books WHERE repo_area = 'incoming' ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        r = import_to_library(str(repo), row[0])
        assert r["ok"] is True
        # Find the operation record
        ops = list_operations(str(repo), op_type="import_to_library")
        assert ops["total"] >= 1
        op_id = ops["items"][0]["operation_id"]
        # Restore it
        r2 = restore_operation(str(repo), op_id)
        assert r2["ok"] is True
        assert r2["source_path"] == r["target_path"]

    def test_restore_updates_repo_area(self):
        repo = _make_repo()
        save_upload(str(repo), "restore2.txt", b"r2")
        from novel_manager.server.services.upload_service import scan_incoming
        scan_incoming(str(repo))
        import sqlite3 as _sql
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        row = conn.execute("SELECT id FROM books WHERE repo_area = 'incoming' ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        import_to_library(str(repo), row[0])
        ops = list_operations(str(repo), op_type="import_to_library")
        restore_operation(str(repo), ops["items"][0]["operation_id"])
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        area = conn.execute("SELECT repo_area FROM books WHERE id = ?", (row[0],)).fetchone()[0]
        conn.close()
        assert area == "incoming"

    def test_cannot_restore_twice(self):
        repo = _make_repo()
        record_operation(str(repo), "import_to_library", 1, "T", "t.txt", "/s/t.txt", "/dst/t.txt", "incoming", "library", reversible=True)
        ops = list_operations(str(repo), op_type="import_to_library")
        op_id = ops["items"][0]["operation_id"]
        # First restore: file exists at target path (book 1's file)
        r1 = restore_operation(str(repo), op_id)
        # Second restore should fail
        r2 = restore_operation(str(repo), op_id)
        assert r2.get("ok") is False

class TestIncomingActions:
    def test_import_to_library_success(self):
        repo = _make_repo()
        result = save_upload(str(repo), "import_test.txt", b"test content")
        scan_incoming(str(repo))
        import sqlite3 as _sql
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        row = conn.execute("SELECT id FROM books WHERE repo_area = 'incoming' ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        assert row is not None
        r = import_to_library(str(repo), row[0])
        assert r["ok"] is True
        assert "library" in r["target_path"]

    def test_import_updates_repo_area(self):
        repo = _make_repo()
        save_upload(str(repo), "area_test.txt", b"test")
        scan_incoming(str(repo))
        import sqlite3 as _sql
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        row = conn.execute("SELECT id FROM books WHERE repo_area = 'incoming' ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        bid = row[0]
        r = import_to_library(str(repo), bid)
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        area = conn.execute("SELECT repo_area FROM books WHERE id = ?", (bid,)).fetchone()[0]
        conn.close()
        assert area == "library"

    def test_import_rejects_non_incoming(self):
        repo = _make_repo()
        r = import_to_library(str(repo), 1)
        assert r.get("ok") is False

    def test_import_rejects_nonexistent(self):
        repo = _make_repo()
        r = import_to_library(str(repo), 99999)
        assert r.get("ok") is False

    def test_move_to_review_duplicates_success(self):
        repo = _make_repo()
        save_upload(str(repo), "revdup_test.txt", b"dup content")
        scan_incoming(str(repo))
        import sqlite3 as _sql
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        row = conn.execute("SELECT id FROM books WHERE repo_area = 'incoming' ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        r = move_to_review_duplicates(str(repo), row[0])
        assert r["ok"] is True
        assert "review_duplicates" in r["target_path"]

    def test_move_to_review_updates_repo_area(self):
        repo = _make_repo()
        save_upload(str(repo), "rd2_test.txt", b"rd2")
        scan_incoming(str(repo))
        import sqlite3 as _sql
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        row = conn.execute("SELECT id FROM books WHERE repo_area = 'incoming' ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        move_to_review_duplicates(str(repo), row[0])
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        area = conn.execute("SELECT repo_area FROM books WHERE id = ?", (row[0],)).fetchone()[0]
        conn.close()
        assert area == "review_duplicates"

    def test_move_rejects_non_incoming(self):
        repo = _make_repo()
        r = move_to_review_duplicates(str(repo), 1)
        assert r.get("ok") is False

    def test_compare_returns_diff(self):
        repo = _make_repo()
        r = compare_books(1, 2, str(repo))
        assert r.get("ok") is True
        assert "diff" in r
        assert "incoming" in r

    def test_compare_nonexistent_fails(self):
        repo = _make_repo()
        r = compare_books(99999, 1, str(repo))
        assert r.get("ok") is False

    def test_no_permanent_delete_calls(self):
        from novel_manager.server.services import incoming_service
        src = open(incoming_service.__file__, 'r', encoding='utf-8').read()
        assert "os.remove" not in src
        assert "os.unlink" not in src
        assert "shutil.rmtree" not in src



        repo = _make_repo()
        save_upload(str(repo), "scan1.txt", b"hello")
        r = scan_incoming(str(repo))
        assert r["found"] >= 1

class TestChapters:
    def test_returns_chapters_list(self):
        repo = _make_repo()
        from novel_manager.server.services.book_service import get_book_chapters
        r = get_book_chapters(str(repo), 1)
        assert r is not None
        assert r["book_id"] == 1
        assert "chapters" in r
        assert len(r["chapters"]) >= 1

    def test_returns_default_when_no_chapters(self):
        repo = _make_repo()
        (repo / "incoming" / "c.txt").write_text("这是没有章节标记的普通文本", encoding="utf-8")
        from novel_manager.server.services.book_service import get_book_chapters
        r = get_book_chapters(str(repo), 3)
        assert r["chapters"][0]["title"] == "全文"
        assert r["chapters"][0]["index"] == 0
        assert r["chapters"][0]["start_offset"] == 0

    def test_nonexistent_book_returns_none(self):
        repo = _make_repo()
        from novel_manager.server.services.book_service import get_book_chapters
        r = get_book_chapters(str(repo), 999)
        assert r is None

    def test_chapters_have_valid_offsets(self):
        repo = _make_repo()
        from novel_manager.server.services.book_service import get_book_chapters
        r = get_book_chapters(str(repo), 1)
        for c in r["chapters"]:
            assert c["start_offset"] >= 0
            assert c["end_offset"] >= c["start_offset"]

    def test_content_api_still_works(self):
        repo = _make_repo()
        r = get_book_content(str(repo), 1)
        assert r is not None
        assert "content" in r

    def test_progress_saves_chapter_index(self):
        repo = _make_repo()
        from novel_manager.server.services.progress_service import save_progress, get_progress
        save_progress(str(repo), 1, 0.5, 1000, current_chapter_index=3)
        p = get_progress(str(repo), 1)
        assert p is not None
        assert p["current_chapter_index"] == 3

    def test_chapters_from_parsed_txt(self):
        repo = _make_repo()
        import sqlite3 as _sql
        multi = "第一章 开始\n正文内容\n第二章 发展\n更多内容\n第三章 结束\n结尾"
        (repo / "library" / "a.txt").write_text(multi, encoding="utf-8")
        conn = _sql.connect(str(repo / "db" / "novel_repo.sqlite"))
        conn.execute("DELETE FROM chapters WHERE book_id = 1")
        conn.commit(); conn.close()
        from novel_manager.server.services.book_service import get_book_chapters
        r = get_book_chapters(str(repo), 1)
        assert len(r["chapters"]) >= 3
        titles = [c["title"] for c in r["chapters"]]
        assert any("第一章" in t for t in titles)
        assert any("第二章" in t for t in titles)
    def test_content_api_unaffected(self):
        repo = _make_repo()
        from novel_manager.server.services.progress_service import save_progress
        save_progress(str(repo), 1, 0.5, 100)
        r = get_book_content(str(repo), 1)
        assert r is not None
        assert "content" in r
