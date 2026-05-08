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
            quality_score REAL, quality_level TEXT, chapter_count INTEGER,
            char_count_clean INTEGER, file_size INTEGER, encoding TEXT,
            reading_status TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS tags (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE IF NOT EXISTS book_tags (book_id INTEGER, tag_id INTEGER);
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY, operation_type TEXT, book_id INTEGER,
            source_path TEXT, target_path TEXT, status TEXT, summary TEXT, applied_at TEXT
        );
    """)
    conn.executemany(
        "INSERT INTO books VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
        assert r["total"] == 3

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
        assert r["repo_revision"] > 0
        assert "server_device_id" in r


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
