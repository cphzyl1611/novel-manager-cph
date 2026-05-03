import json
import sqlite3
import uuid
from pathlib import Path

from novel_manager.db import initialize, upsert_book
from novel_manager.metadata_tools import post_rename_check, refresh_metadata, write_post_rename_check_reports
from novel_manager.operations import log_operation
from novel_manager.report_index import list_reports
from novel_manager.summary_report import generate_summary_report


def make_repo() -> Path:
    root = Path(".tmp") / "metadata_tools_tests" / uuid.uuid4().hex
    for rel in ["library", "incoming", "review_duplicates", "reports/health", "logs"]:
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize(conn)
    return conn


def book(path: Path, *, area: str = "library", file_name: str | None = None, title_norm: str = "old") -> dict:
    return {
        "current_path": str(path),
        "original_path": str(path),
        "repo_area": area,
        "file_name": file_name or path.name,
        "file_size": path.stat().st_size if path.exists() else 0,
        "mtime": 1.0,
        "raw_sha256": "raw-" + path.name,
        "clean_sha256": "clean-" + path.name,
        "title_raw": title_norm,
        "title_norm": title_norm,
        "author_raw": "",
        "author_norm": "",
        "encoding": "utf-8",
        "encoding_confidence": 1.0,
        "decode_status": "ok",
        "char_count_raw": 100,
        "char_count_clean": 100,
        "line_count_raw": 10,
        "line_count_clean": 10,
        "chapter_count": 2,
        "mojibake_rate": 0.0,
        "ad_line_count": 0,
        "ad_line_rate": 0.0,
        "duplicate_chapter_count": 0,
        "missing_chapter_count": 0,
        "chapter_order_error_count": 0,
        "truncated_risk": 0,
        "quality_score": 90,
        "quality_level": "good",
        "quality_reasons_json": "[]",
        "status": "active",
        "reading_status": None,
        "created_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-02 00:00:00",
    }


def seed(conn, repo, name="新书 - 作者.txt", **kwargs):
    path = repo / "library" / name
    path.write_text("content", encoding="utf-8")
    book_id = upsert_book(conn, book(path, **kwargs))
    return book_id, path


def test_operations_log_utf8_reason_and_json():
    repo = make_repo()
    with memory_conn() as conn:
        log_operation(
            conn,
            repo,
            operation_type="test",
            book_id=None,
            source_path="",
            target_path="",
            raw_sha256_before=None,
            raw_sha256_after=None,
            status="success",
            report_path=None,
            reason="添加标签：高质量；旧乱码：楂樿川閲?",
        )
        reason = conn.execute("SELECT reason FROM operations").fetchone()[0]
    text = (repo / "logs" / "operations.log").read_text(encoding="utf-8")
    assert "高质量" in reason
    assert "高质量" in text
    assert "\\u9ad8" not in text


def test_refresh_metadata_dry_run_and_apply():
    repo = make_repo()
    with memory_conn() as conn:
        book_id, path = seed(conn, repo, "高考陪读那三年 - 张三 [完本].txt", title_norm="高考陪读那三年 p站正式版本")
        dry = refresh_metadata(conn, repo, dry_run=True, book_id=book_id)
        row = conn.execute("SELECT title_norm, author_norm FROM books WHERE id = ?", (book_id,)).fetchone()
        assert dry["items"][0]["status"] == "dry_run"
        assert row["title_norm"] == "高考陪读那三年 p站正式版本"
        applied = refresh_metadata(conn, repo, apply=True, book_id=book_id)
        row = conn.execute("SELECT file_name, title_norm, author_norm FROM books WHERE id = ?", (book_id,)).fetchone()
        ops = conn.execute("SELECT operation_type FROM operations").fetchone()[0]
    assert applied["updated_count"] == 1
    assert row["file_name"] == path.name
    assert row["title_norm"] == "高考陪读那三年"
    assert row["author_norm"] == "张三"
    assert ops == "refresh_metadata"


def test_refresh_metadata_keeps_title_when_filename_has_status_suffix():
    repo = make_repo()
    with memory_conn() as conn:
        book_id, _ = seed(conn, repo, "高考陪读那三年 [正式版].txt", title_norm="高考陪读那三年 p站正式版本")
        result = refresh_metadata(conn, repo, dry_run=True, book_id=book_id)
    assert result["items"][0]["new_title_norm"] == "高考陪读那三年"


def test_refresh_metadata_missing_book_id_query_and_no_change():
    repo = make_repo()
    with memory_conn() as conn:
        first_id, first_path = seed(conn, repo, "第一本.txt", title_norm="第一本")
        second_id, second_path = seed(conn, repo, "第二本.txt", title_norm="noise")
        first_path.unlink()
        missing = refresh_metadata(conn, repo, dry_run=True, book_id=first_id)
        queried = refresh_metadata(conn, repo, dry_run=True, query="第二")
        no_change = refresh_metadata(conn, repo, apply=True, book_id=second_id)
    assert missing["items"][0]["status"] == "skipped"
    assert queried["total"] == 1
    assert queried["items"][0]["book_id"] == second_id
    assert no_change["updated_count"] == 1 or no_change["no_change_count"] == 1


def test_post_rename_check_detects_issues_and_writes_reports():
    repo = make_repo()
    with memory_conn() as conn:
        missing_path = repo / "library" / "missing.txt"
        upsert_book(conn, book(missing_path, title_norm="clean"))
        dirty_path = repo / "incoming" / "[sxsy.org]旧书.txt.txt"
        dirty_path.write_text("content", encoding="utf-8")
        upsert_book(conn, book(dirty_path, area="library", file_name="wrong.txt", title_norm="sxsy old txt"))
        payload = post_rename_check(conn, repo)
        html, js, md = write_post_rename_check_reports(repo, payload)
    codes = {issue["code"] for issue in payload["issues"]}
    assert {"missing_file", "metadata_mismatch", "dirty_file_name", "dirty_title_norm", "repo_area_path_mismatch"} <= codes
    assert html.exists()
    assert js.exists()
    assert md.exists()
    assert "post_rename_check" in js.name


def test_summary_and_report_index_include_health_report():
    repo = make_repo()
    payload = {
        "stats": {
            "error_count": 1,
            "warning_count": 2,
            "missing_file_count": 1,
            "dirty_file_name_count": 1,
            "dirty_title_norm_count": 1,
            "metadata_mismatch_count": 1,
        },
        "issues": [],
        "ok": [],
    }
    path = repo / "reports" / "health" / "post_rename_check_20260101_010101.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    text = generate_summary_report(repo).read_text(encoding="utf-8")
    reports = list_reports(repo, report_type="health")
    assert "健康检查汇总" in text
    assert "post_rename_check" in reports[0]["file_name"]
