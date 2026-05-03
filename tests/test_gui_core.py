import json
import sqlite3
import uuid
from pathlib import Path

from novel_manager.db import initialize, upsert_book
from novel_manager.gui.command_runner import build_cli_command, ensure_gui_safe_command, is_command_allowed_in_gui
from novel_manager.gui.i18n import action_label, area_label, group_type_label, quality_label, risk_label
from novel_manager.gui.report_loaders import (
    collect_issue_summary,
    load_duplicate_report,
    load_health_report,
    load_rename_plan,
    load_update_report,
    parse_operation_line,
    summarize_report,
    summarize_operation_record,
)
from novel_manager.gui.repo_state import (
    detect_plain_txt_folder,
    get_db_path,
    get_repo_structure_status,
    import_txt_folder_to_library,
    is_initialized_repo,
    load_books,
    load_dashboard_stats,
    load_recent_operations,
    load_reports,
)
from novel_manager.gui.safe_actions import is_safe_rename_item, is_safe_update_item, write_filtered_rename_plan, write_filtered_update_report


def make_repo() -> Path:
    root = Path(".tmp") / "gui_core_tests" / uuid.uuid4().hex
    for rel in ["db", "config", "library", "incoming", "reports/quality", "reports/health", "reports/duplicate", "reports/rename", "reports/update", "logs"]:
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def book(path: Path, area: str = "library", quality_level: str = "good") -> dict:
    return {
        "current_path": str(path),
        "original_path": str(path),
        "repo_area": area,
        "file_name": path.name,
        "file_size": 1,
        "mtime": 1.0,
        "raw_sha256": "raw" + path.name,
        "clean_sha256": "clean" + path.name,
        "title_raw": "测试书",
        "title_norm": "测试书",
        "author_raw": "作者",
        "author_norm": "作者",
        "encoding": "utf-8",
        "encoding_confidence": 1.0,
        "decode_status": "ok",
        "char_count_raw": 100,
        "char_count_clean": 100,
        "line_count_raw": 10,
        "line_count_clean": 10,
        "chapter_count": 2,
        "mojibake_rate": 0.1 if quality_level == "poor" else 0.0,
        "ad_line_count": 2 if quality_level == "poor" else 0,
        "ad_line_rate": 0.0,
        "duplicate_chapter_count": 0,
        "missing_chapter_count": 1 if quality_level == "poor" else 0,
        "chapter_order_error_count": 0,
        "truncated_risk": 0,
        "quality_score": 40 if quality_level == "poor" else 90,
        "quality_level": quality_level,
        "quality_reasons_json": "[]",
        "status": "active",
        "reading_status": "未读",
        "created_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-02 00:00:00",
    }


def test_repo_state_reads_books_from_sqlite():
    repo = make_repo()
    path = repo / "library" / "测试书.txt"
    path.write_text("x", encoding="utf-8")
    conn = sqlite3.connect(get_db_path(repo))
    conn.row_factory = sqlite3.Row
    initialize(conn)
    upsert_book(conn, book(path))
    conn.close()
    rows = load_books(repo, {"query": "测试", "area": "library"})
    stats = load_dashboard_stats(repo)
    assert len(rows) == 1
    assert rows[0]["title_norm"] == "测试书"
    assert stats["books"] == 1
    assert is_initialized_repo(repo)
    assert get_repo_structure_status(repo)["kind"] == "initialized_repo"


def test_repo_state_scans_reports_directory():
    repo = make_repo()
    (repo / "reports" / "quality" / "quality_report_test.html").write_text("<html></html>", encoding="utf-8")
    (repo / "reports" / "health" / "post_rename_check_test.md").write_text("# ok", encoding="utf-8")
    reports = load_reports(repo)
    types = {item["report_type"] for item in reports}
    assert {"quality", "health"} <= types


def test_command_builder_and_safety_rules():
    command = build_cli_command("python", "scan", "D:/Repo", ["--area", "library"])
    assert command[:4] == ["python", str(Path(command[1])), "scan", "--repo"]
    assert is_command_allowed_in_gui("scan", ["--area", "library"])[0] is True
    assert is_command_allowed_in_gui("apply-renames", ["--report", "r.json", "--dry-run"])[0] is True
    assert is_command_allowed_in_gui("apply-renames", ["--report", "r.json", "--confirm"])[0] is False
    assert ensure_gui_safe_command("stage-duplicates", ["--report", "r.json", "--dry-run"])[0] is True
    assert ensure_gui_safe_command("stage-duplicates", ["--report", "r.json", "--confirm"])[0] is False
    assert ensure_gui_safe_command("move-to-trash", ["--book-id", "1", "--dry-run"])[0] is True
    assert ensure_gui_safe_command("move-to-trash", ["--book-id", "1", "--confirm", "--yes-i-understand"])[0] is False
    assert is_command_allowed_in_gui("refresh-metadata", ["--apply"])[0] is False
    assert is_command_allowed_in_gui("auto-tag", ["--dry-run"])[0] is True


def test_i18n_labels():
    assert group_type_label("near_duplicate") == "近似重复"
    assert action_label("rename_recommended") == "建议改名"
    assert action_label("manual_review") == "需要人工确认"
    assert risk_label("dirty_file_name") == "文件名仍含噪声"
    assert quality_label("excellent") == "优秀"
    assert area_label("library") == "小说库"


def test_plain_txt_folder_detection_and_import_helper():
    repo = make_repo()
    source = Path(".tmp") / "gui_import_tests" / uuid.uuid4().hex
    source.mkdir(parents=True)
    (source / "A.txt").write_text("a", encoding="utf-8")
    (repo / "library" / "A.txt").write_text("old", encoding="utf-8")
    info = detect_plain_txt_folder(source)
    dry = import_txt_folder_to_library(source, repo, dry_run=True)
    assert info["is_plain_txt_folder"] is True
    assert dry["found_count"] == 1
    assert not (repo / "library" / "A_1.txt").exists()
    applied = import_txt_folder_to_library(source, repo, dry_run=False, apply=True)
    assert applied["copied_count"] == 1
    assert (repo / "library" / "A_1.txt").exists()


def write_reports(repo: Path) -> None:
    (repo / "reports" / "duplicate" / "duplicate_report_test.json").write_text(
        json.dumps({"groups": [{"group_type": "near_duplicate", "recommended_action": "manual_review"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (repo / "reports" / "rename" / "rename_plan_test.json").write_text(
        json.dumps({"suggestions": [{"action": "rename_recommended"}, {"action": "manual_review"}, {"risk_flags": ["target_name_conflict"]}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (repo / "reports" / "update" / "update_report_test.json").write_text(
        json.dumps({"candidates": [{"recommendation": "replace_recommended"}, {"recommendation": "review"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (repo / "reports" / "health" / "post_rename_check_test.json").write_text(
        json.dumps({"issues": [{"severity": "warning", "code": "dirty_file_name"}, {"severity": "error", "code": "dirty_title_norm"}]}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_report_loaders_are_tolerant_and_generate_chinese_summary():
    repo = make_repo()
    write_reports(repo)
    duplicate = load_duplicate_report(repo / "reports" / "duplicate" / "duplicate_report_test.json")
    rename = load_rename_plan(repo / "reports" / "rename" / "rename_plan_test.json")
    update = load_update_report(repo / "reports" / "update" / "update_report_test.json")
    health = load_health_report(repo / "reports" / "health" / "post_rename_check_test.json")
    assert "近似重复" in duplicate["summary_text"]
    assert "建议改名" in rename["summary_text"]
    assert summarize_report(update)["replace_recommended"] == 1
    assert summarize_report(health)["warnings"] == 1
    assert load_duplicate_report(repo / "missing.json")["ok"] is False
    assert load_update_report(repo / "reports" / "update" / "bad.json")["candidates"] == []


def test_issues_page_data_aggregation_from_reports_and_books():
    repo = make_repo()
    write_reports(repo)
    conn = sqlite3.connect(get_db_path(repo))
    conn.row_factory = sqlite3.Row
    initialize(conn)
    incoming = repo / "incoming" / "新书.txt"
    incoming.write_text("x", encoding="utf-8")
    poor = repo / "library" / "差书.txt"
    poor.write_text("x", encoding="utf-8")
    upsert_book(conn, book(incoming, "incoming"))
    upsert_book(conn, book(poor, "library", "poor"))
    conn.close()
    summary = collect_issue_summary(repo)
    assert summary["duplicate"]["near"] == 1
    assert summary["update"]["incoming"] == 1
    assert summary["rename"]["recommended"] == 1
    assert summary["health"]["dirty_file_name"] == 1
    assert summary["quality"]["low_quality"] == 1
    assert collect_issue_summary(Path(".tmp") / uuid.uuid4().hex)["has_data"] is False


def test_gui_source_does_not_call_permanent_delete():
    gui_source = "\n".join(path.read_text(encoding="utf-8") for path in Path("novel_manager/gui").rglob("*.py"))
    assert "os.remove" not in gui_source
    assert ".unlink(" not in gui_source


def test_operation_log_parsing_uses_chinese_summary_not_raw_json():
    record = {
        "operation_type": "apply_rename",
        "status": "success",
        "book_id": 1,
        "source_path": "D:/repo/library/old.txt",
        "target_path": "D:/repo/library/new.txt",
        "created_at": "2026-01-01 18:06:00",
    }
    summary = summarize_operation_record(record)
    assert "执行重命名" in summary
    assert "operation_type" not in summary
    parsed = parse_operation_line(json.dumps(record, ensure_ascii=False))
    assert "执行重命名" in parsed["summary"]


def test_recent_operations_returns_summaries():
    repo = make_repo()
    (repo / "logs" / "operations.log").write_text(
        json.dumps({"operation_type": "apply_rename", "status": "success", "target_path": "new.txt"}, ensure_ascii=False),
        encoding="utf-8",
    )
    rows = load_recent_operations(repo)
    assert rows == ["执行重命名：成功，new.txt"]
