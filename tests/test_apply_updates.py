import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from novel_manager.apply_updates import apply_updates_from_report
from novel_manager.cli import main
from novel_manager.db import initialize, upsert_book
from novel_manager.summary_report import generate_summary_report
from novel_manager.work_groups import apply_group_candidates, migrate_work_group_schema


def make_repo():
    root = Path(".tmp") / "apply_updates_tests" / uuid.uuid4().hex
    for rel in ["library", "incoming", "archive/replaced", "reports/update", "logs"]:
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def memory_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    initialize(conn)
    migrate_work_group_schema(conn)
    return conn


def book(path, area, title="书", score=90):
    p = Path(path)
    return {
        "current_path": str(p),
        "original_path": str(p),
        "repo_area": area,
        "file_name": p.name,
        "file_size": p.stat().st_size if p.exists() else 0,
        "mtime": 1.0,
        "raw_sha256": "r" + p.name,
        "clean_sha256": "c" + p.name,
        "title_raw": title,
        "title_norm": title,
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
        "mojibake_rate": 0.0,
        "ad_line_count": 0,
        "ad_line_rate": 0.0,
        "duplicate_chapter_count": 0,
        "missing_chapter_count": 0,
        "chapter_order_error_count": 0,
        "truncated_risk": 0,
        "quality_score": score,
        "quality_level": "good",
        "quality_reasons_json": "[]",
        "status": "active",
        "reading_status": None,
        "created_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-02 00:00:00",
    }


def report(repo, candidates):
    path = repo / "reports" / "update" / "update_report_test.json"
    path.write_text(json.dumps({"candidates": candidates}, ensure_ascii=False), encoding="utf-8")
    return path


def candidate(old_id, new_id, **overrides):
    data = {
        "old_book_id": old_id,
        "new_book_id": new_id,
        "recommendation": "replace_recommended",
        "same_work_score": 0.95,
        "coverage_score": 0.95,
        "new_content_score": 0.5,
        "quality_delta": 0,
        "risk_flags": [],
        "reason_summary": "safe update",
    }
    data.update(overrides)
    return data


def seed(conn, repo, old_name="old.txt", new_name="new.txt"):
    old_path = repo / "library" / old_name
    new_path = repo / "incoming" / new_name
    old_path.write_text("old content", encoding="utf-8")
    new_path.write_text("new content", encoding="utf-8")
    old_id = upsert_book(conn, book(old_path, "library"))
    new_id = upsert_book(conn, book(new_path, "incoming"))
    return old_id, new_id, old_path, new_path


def test_dry_run_no_move_no_db_update():
    repo = make_repo()
    with memory_conn() as conn:
        old_id, new_id, old_path, new_path = seed(conn, repo)
        log = apply_updates_from_report(conn, repo, report(repo, [candidate(old_id, new_id)]), dry_run=True)
        old = conn.execute("SELECT repo_area FROM books WHERE id = ?", (old_id,)).fetchone()[0]
    assert old_path.exists()
    assert new_path.exists()
    assert old == "library"
    assert log["planned_count"] == 1
    assert log["dry_run"] is True


def test_cli_confirm_safety_gate(capsys):
    assert main(["apply-updates", "--repo", "X", "--report", "r.json"]) == 2
    assert main(["apply-updates", "--repo", "X", "--report", "r.json", "--confirm"]) == 2
    with pytest.raises(SystemExit):
        main(["apply-updates", "--repo", "X", "--report", "r.json", "--dry-run", "--confirm"])
    out = capsys.readouterr().out
    assert "--dry-run" in out or "--yes-i-understand" in out


def test_filter_rules_skip_unsafe_candidates():
    repo = make_repo()
    with memory_conn() as conn:
        old_id, new_id, *_ = seed(conn, repo)
        candidates = [
            candidate(old_id, new_id, recommendation="manual_review"),
            candidate(old_id, new_id, recommendation="reject"),
            candidate(old_id, new_id, same_work_score=0.1),
            candidate(old_id, new_id, coverage_score=0.1),
            candidate(old_id, new_id, quality_delta=-99),
            candidate(old_id, new_id, risk_flags=["author_conflict"]),
        ]
        log = apply_updates_from_report(conn, repo, report(repo, candidates), dry_run=True)
    assert log["planned_count"] == 0
    assert log["skipped_count"] == 6


def test_success_replace_moves_files_updates_db_operations_and_log():
    repo = make_repo()
    with memory_conn() as conn:
        old_id, new_id, old_path, new_path = seed(conn, repo, new_name="old.txt")
        (repo / "library" / "old.txt").write_text("existing library name", encoding="utf-8")
        # reset old file after deliberate collision setup
        old_path.write_text("old content", encoding="utf-8")
        log = apply_updates_from_report(conn, repo, report(repo, [candidate(old_id, new_id)]), confirm=True)
        old = conn.execute("SELECT current_path, repo_area, status FROM books WHERE id = ?", (old_id,)).fetchone()
        new = conn.execute("SELECT current_path, repo_area, status FROM books WHERE id = ?", (new_id,)).fetchone()
        ops = conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
    assert not old_path.exists()
    assert not new_path.exists()
    assert Path(old["current_path"]).exists()
    assert Path(new["current_path"]).exists()
    assert old["repo_area"] == "archive"
    assert new["repo_area"] == "library"
    assert old["status"] == "archived"
    assert ops == 2
    assert Path(log["log_path"]).exists()


def test_work_group_same_group_and_old_group_new_without_group():
    repo = make_repo()
    with memory_conn() as conn:
        old_id, new_id, *_ = seed(conn, repo)
        apply_group_candidates(
            conn,
            [
                {
                    "canonical_title": "书",
                    "canonical_author": "作者",
                    "recommended_primary_book_id": old_id,
                    "group_confidence": 1.0,
                    "group_source": "test",
                    "group_reason": "test",
                    "manual_review": False,
                    "members": [{"book_id": old_id, "role": "primary", "confidence": 1.0, "source": "test", "member_reason": "test"}],
                }
            ],
        )
        apply_updates_from_report(conn, repo, report(repo, [candidate(old_id, new_id)]), confirm=True)
        group = conn.execute("SELECT primary_book_id FROM work_groups").fetchone()[0]
        roles = {row["book_id"]: row["role"] for row in conn.execute("SELECT book_id, role FROM book_group_members").fetchall()}
    assert group == new_id
    assert roles[old_id] == "old_version"
    assert roles[new_id] == "primary"


def test_group_conflict_recorded_without_merge():
    repo = make_repo()
    with memory_conn() as conn:
        old_id, new_id, *_ = seed(conn, repo)
        for bid in (old_id, new_id):
            apply_group_candidates(
                conn,
                [
                    {
                        "canonical_title": f"书{bid}",
                        "canonical_author": "作者",
                        "recommended_primary_book_id": bid,
                        "group_confidence": 1.0,
                        "group_source": "test",
                        "group_reason": "test",
                        "manual_review": False,
                        "members": [{"book_id": bid, "role": "primary", "confidence": 1.0, "source": "test", "member_reason": "test"}],
                    }
                ],
            )
        log = apply_updates_from_report(conn, repo, report(repo, [candidate(old_id, new_id)]), confirm=True)
    assert log["items"][0]["group_note"] == "group_conflict"


def test_missing_paths_skip_and_batch_continues():
    repo = make_repo()
    with memory_conn() as conn:
        old1, new1, old_path, _ = seed(conn, repo, "old1.txt", "new1.txt")
        old2, new2, *_ = seed(conn, repo, "old2.txt", "new2.txt")
        old_path.unlink()
        log = apply_updates_from_report(conn, repo, report(repo, [candidate(old1, new1), candidate(old2, new2)]), confirm=True)
    assert log["skipped_count"] == 1
    assert log["applied_count"] == 1


def test_summary_report_reads_apply_log():
    repo = make_repo()
    log_path = repo / "logs" / "apply_updates_20260101_010101.json"
    log_path.write_text(json.dumps({"dry_run": True, "confirm": False, "planned_count": 1, "applied_count": 0, "skipped_count": 0, "failed_count": 0}), encoding="utf-8")
    text = generate_summary_report(repo).read_text(encoding="utf-8")
    assert "更新应用汇总" in text
    assert "planned_count" in text
