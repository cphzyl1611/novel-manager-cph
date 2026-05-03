import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from novel_manager.apply_renames import apply_renames_from_report
from novel_manager.cli import main
from novel_manager.db import initialize, upsert_book
from novel_manager.summary_report import generate_summary_report


def make_repo() -> Path:
    root = Path(".tmp") / "apply_renames_tests" / uuid.uuid4().hex
    for rel in ["library", "reports/rename", "logs"]:
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize(conn)
    return conn


def book(path: Path, title: str = "Book") -> dict:
    return {
        "current_path": str(path),
        "original_path": str(path),
        "repo_area": "library",
        "file_name": path.name,
        "file_size": path.stat().st_size if path.exists() else 0,
        "mtime": 1.0,
        "raw_sha256": "raw-" + path.name,
        "clean_sha256": "clean-" + path.name,
        "title_raw": title,
        "title_norm": title,
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


def suggestion(book_id: int, current_name: str, target_name: str, **overrides) -> dict:
    data = {
        "book_id": book_id,
        "current_file_name": current_name,
        "current_path": "",
        "target_file_name": target_name,
        "target_path_preview": "",
        "action": "rename_recommended",
        "risk_flags": [],
        "reason_summary": "safe rename",
    }
    data.update(overrides)
    return data


def report(repo: Path, suggestions: list[dict]) -> Path:
    path = repo / "reports" / "rename" / "rename_plan_test.json"
    path.write_text(json.dumps({"suggestions": suggestions}, ensure_ascii=False), encoding="utf-8")
    return path


def seed(conn: sqlite3.Connection, repo: Path, name: str = "old.txt", content: str = "content"):
    path = repo / "library" / name
    path.write_text(content, encoding="utf-8")
    book_id = upsert_book(conn, book(path))
    return book_id, path


def operation_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0])


def test_dry_run_does_not_rename_update_db_or_write_operations():
    repo = make_repo()
    with memory_conn() as conn:
        book_id, old_path = seed(conn, repo)
        log = apply_renames_from_report(conn, repo, report(repo, [suggestion(book_id, old_path.name, "new.txt")]), dry_run=True)
        row = conn.execute("SELECT current_path, file_name FROM books WHERE id = ?", (book_id,)).fetchone()
        assert old_path.exists()
        assert not (repo / "library" / "new.txt").exists()
        assert row["current_path"] == str(old_path)
        assert row["file_name"] == "old.txt"
        assert operation_count(conn) == 0
    assert log["planned_count"] == 1
    assert log["renamed_count"] == 0
    assert Path(log["log_path"]).exists()


def test_cli_confirm_safety_gate(capsys):
    assert main(["apply-renames", "--repo", "X", "--report", "r.json"]) == 2
    assert main(["apply-renames", "--repo", "X", "--report", "r.json", "--confirm"]) == 2
    with pytest.raises(SystemExit):
        main(["apply-renames", "--repo", "X", "--report", "r.json", "--dry-run", "--confirm"])
    out = capsys.readouterr().out
    assert "--dry-run" in out or "--yes-i-understand" in out


def test_filter_rules_skip_unsafe_suggestions():
    repo = make_repo()
    with memory_conn() as conn:
        book_id, old_path = seed(conn, repo)
        suggestions = [
            suggestion(book_id, old_path.name, "a.txt", action="manual_review"),
            suggestion(book_id, old_path.name, "b.txt", action="no_change"),
            suggestion(book_id, old_path.name, "c.txt", risk_flags=["target_name_conflict"]),
            suggestion(book_id, old_path.name, "d.txt", risk_flags=["duplicate_book_group"]),
            suggestion(book_id, old_path.name, "e.txt", risk_flags=["author_suspicious"]),
            suggestion(book_id, old_path.name, "subdir/f.txt"),
        ]
        log = apply_renames_from_report(conn, repo, report(repo, suggestions), dry_run=True)
    assert log["planned_count"] == 0
    assert log["skipped_count"] == 6


def test_duplicate_book_group_can_be_allowed():
    repo = make_repo()
    with memory_conn() as conn:
        book_id, old_path = seed(conn, repo)
        path = report(repo, [suggestion(book_id, old_path.name, "new.txt", risk_flags=["duplicate_book_group"])])
        blocked = apply_renames_from_report(conn, repo, path, dry_run=True)
        allowed = apply_renames_from_report(conn, repo, path, dry_run=True, allow_duplicate_book_group=True)
    assert blocked["planned_count"] == 0
    assert allowed["planned_count"] == 1


def test_successful_confirm_renames_updates_db_operations_and_logs():
    repo = make_repo()
    with memory_conn() as conn:
        book_id, old_path = seed(conn, repo)
        log = apply_renames_from_report(
            conn,
            repo,
            report(repo, [suggestion(book_id, old_path.name, "new.txt")]),
            confirm=True,
        )
        row = conn.execute("SELECT current_path, file_name, repo_area FROM books WHERE id = ?", (book_id,)).fetchone()
        ops = conn.execute("SELECT operation_type, source_path, target_path FROM operations").fetchone()
    new_path = repo / "library" / "new.txt"
    assert not old_path.exists()
    assert new_path.exists()
    assert row["current_path"] == str(new_path)
    assert row["file_name"] == "new.txt"
    assert row["repo_area"] == "library"
    assert ops["operation_type"] == "apply_rename"
    assert old_path.name in ops["source_path"]
    assert new_path.name in ops["target_path"]
    assert "apply_rename" in (repo / "logs" / "operations.log").read_text(encoding="utf-8")
    assert log["renamed_count"] == 1
    assert Path(log["log_path"]).exists()


def test_target_exists_and_missing_path_skip_and_batch_continues():
    repo = make_repo()
    with memory_conn() as conn:
        first_id, first_path = seed(conn, repo, "first.txt", "first")
        second_id, second_path = seed(conn, repo, "second.txt", "second")
        third_id, third_path = seed(conn, repo, "third.txt", "third")
        (repo / "library" / "exists.txt").write_text("occupied", encoding="utf-8")
        second_path.unlink()
        log = apply_renames_from_report(
            conn,
            repo,
            report(
                repo,
                [
                    suggestion(first_id, first_path.name, "exists.txt"),
                    suggestion(second_id, second_path.name, "missing-renamed.txt"),
                    suggestion(third_id, third_path.name, "third-renamed.txt"),
                ],
            ),
            confirm=True,
        )
        third = conn.execute("SELECT file_name FROM books WHERE id = ?", (third_id,)).fetchone()[0]
    assert log["skipped_count"] == 2
    assert log["renamed_count"] == 1
    assert third == "third-renamed.txt"


def test_summary_report_reads_apply_renames_log():
    repo = make_repo()
    path = repo / "logs" / "apply_renames_20260101_010101.json"
    path.write_text(
        json.dumps(
            {
                "dry_run": True,
                "confirm": False,
                "planned_count": 2,
                "renamed_count": 0,
                "skipped_count": 1,
                "failed_count": 0,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    text = generate_summary_report(repo).read_text(encoding="utf-8")
    assert "重命名应用汇总" in text
    assert "planned_count" in text
