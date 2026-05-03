from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .fingerprint import sha256_file
from .operations import clean_log_text
from .utils import ensure_dir, file_ts, now_ts, read_json, write_json

SEVERE_RISKS = {
    "author_conflict",
    "low_same_work_score",
    "low_coverage",
    "no_new_content",
    "mojibake_increase",
    "ad_line_increase",
    "possible_truncated_new_version",
}


def _unique_path(path: Path, marker: str = "__dup") -> Path:
    if not path.exists():
        return path
    for index in range(1, 10000):
        candidate = path.with_name(f"{path.stem}{marker}{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"could not create unique path for {path}")


def _archive_target(repo: Path, old_book_id: int, old_path: Path, ts: str) -> Path:
    suffix = old_path.suffix or ".txt"
    target = repo / "archive" / "replaced" / f"{old_path.stem}__replaced_at_{ts}__book{old_book_id}{suffix}"
    return _unique_path(target, "__dup")


def _library_target(repo: Path, new_path: Path, ts: str) -> Path:
    target = repo / "library" / new_path.name
    if not target.exists():
        return target
    return _unique_path(repo / "library" / f"{new_path.stem}__from_incoming_{ts}{new_path.suffix}", "__dup")


def _book(conn: sqlite3.Connection, book_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    return dict(row) if row else None


def _score(candidate: dict[str, Any], key: str) -> float:
    try:
        return float(candidate.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _skip_reason(candidate: dict[str, Any], *, min_same_work_score: float, min_coverage: float, max_quality_drop: float, allow_risk: bool) -> str | None:
    if candidate.get("approved") is False:
        return "approved=false"
    if candidate.get("recommendation") != "replace_recommended":
        return "recommendation is not replace_recommended"
    if _score(candidate, "same_work_score") < min_same_work_score:
        return "same_work_score below threshold"
    if _score(candidate, "coverage_score") < min_coverage:
        return "coverage_score below threshold"
    if _score(candidate, "quality_delta") < -max_quality_drop:
        return "quality_delta below threshold"
    risks = set(candidate.get("risk_flags") or [])
    if "author_conflict" in risks:
        return "author_conflict risk"
    severe = risks & SEVERE_RISKS
    if severe and not allow_risk:
        return "severe risk flags: " + ",".join(sorted(severe))
    return None


def _append_operation_log(repo: Path, record: dict[str, Any]) -> None:
    log_path = repo / "logs" / "operations.log"
    ensure_dir(log_path.parent)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _operation(
    conn: sqlite3.Connection,
    repo: Path,
    *,
    operation_type: str,
    book_id: int,
    source_path: str,
    target_path: str,
    before: str | None,
    after: str | None,
    status: str,
    report_path: str,
    reason: str,
) -> None:
    created = now_ts()
    reason = clean_log_text(reason)
    conn.execute(
        """
        INSERT INTO operations
        (operation_type, book_id, source_path, target_path, raw_sha256_before, raw_sha256_after,
         status, report_path, reason, created_at, applied_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (operation_type, book_id, source_path, target_path, before, after, status, report_path, reason, created, created),
    )
    record = {
        "operation_type": operation_type,
        "book_id": book_id,
        "source_path": source_path,
        "target_path": target_path,
        "raw_sha256_before": before,
        "raw_sha256_after": after,
        "status": status,
        "report_path": report_path,
        "reason": reason,
        "created_at": created,
    }
    _append_operation_log(repo, record)


def _groups_for(conn: sqlite3.Connection, book_id: int) -> set[int]:
    try:
        rows = conn.execute("SELECT work_group_id FROM book_group_members WHERE book_id = ?", (book_id,)).fetchall()
    except sqlite3.Error:
        return set()
    return {int(row["work_group_id"]) for row in rows}


def _update_groups(conn: sqlite3.Connection, old_book_id: int, new_book_id: int, now: str) -> str | None:
    old_groups = _groups_for(conn, old_book_id)
    new_groups = _groups_for(conn, new_book_id)
    if old_groups and new_groups and old_groups == new_groups:
        group_id = next(iter(old_groups))
        conn.execute("UPDATE book_group_members SET role = 'old_version', updated_at = ? WHERE work_group_id = ? AND book_id = ?", (now, group_id, old_book_id))
        conn.execute("UPDATE book_group_members SET role = 'primary', updated_at = ? WHERE work_group_id = ? AND book_id = ?", (now, group_id, new_book_id))
        conn.execute("UPDATE work_groups SET primary_book_id = ?, updated_at = ? WHERE id = ?", (new_book_id, now, group_id))
        return None
    if old_groups and not new_groups:
        group_id = next(iter(old_groups))
        conn.execute(
            "INSERT INTO book_group_members (work_group_id, book_id, role, confidence, source, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (group_id, new_book_id, "primary", 1.0, "apply_update", "promoted incoming update", now, now),
        )
        conn.execute("UPDATE book_group_members SET role = 'old_version', updated_at = ? WHERE work_group_id = ? AND book_id = ?", (now, group_id, old_book_id))
        conn.execute("UPDATE work_groups SET primary_book_id = ?, updated_at = ? WHERE id = ?", (new_book_id, now, group_id))
        return None
    if old_groups and new_groups and old_groups != new_groups:
        return "group_conflict"
    return None


def _move_verified(source: Path, target: Path) -> tuple[str, str]:
    ensure_dir(target.parent)
    before = sha256_file(source)
    shutil.move(str(source), str(target))
    after = sha256_file(target)
    if before != after:
        raise IOError("hash mismatch after move")
    return before, after


def _candidate_plan(repo: Path, candidate: dict[str, Any], old_book: dict[str, Any], new_book: dict[str, Any], ts: str) -> dict[str, Any]:
    old_source = Path(old_book["current_path"])
    new_source = Path(new_book["current_path"])
    return {
        "old_archive_path": str(_archive_target(repo, old_book["id"], old_source, ts)),
        "new_library_path": str(_library_target(repo, new_source, ts)),
    }


def apply_updates_from_report(
    conn: sqlite3.Connection,
    repo: Path,
    report: Path,
    *,
    dry_run: bool = False,
    confirm: bool = False,
    min_same_work_score: float = 0.85,
    min_coverage: float = 0.90,
    max_quality_drop: float = 5,
    allow_risk: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    if dry_run and confirm:
        raise ValueError("--dry-run and --confirm cannot be used together")
    if not dry_run and not confirm:
        raise ValueError("use dry_run=True or confirm=True")
    report_path = report
    if not report_path.is_absolute() and not report_path.exists():
        report_path = repo / report_path
    payload = read_json(report_path)
    candidates = payload.get("candidates") or []
    ts = file_ts()
    results: list[dict[str, Any]] = []
    planned = 0
    applied = 0
    skipped = 0
    failed = 0
    for candidate in candidates:
        if limit is not None and planned >= limit:
            break
        item = {
            "old_book_id": candidate.get("old_book_id"),
            "new_book_id": candidate.get("new_book_id"),
            "recommendation": candidate.get("recommendation"),
            "scores": {
                "same_work_score": candidate.get("same_work_score"),
                "coverage_score": candidate.get("coverage_score"),
                "new_content_score": candidate.get("new_content_score"),
                "quality_delta": candidate.get("quality_delta"),
            },
            "risk_flags": candidate.get("risk_flags") or [],
        }
        reason = _skip_reason(candidate, min_same_work_score=min_same_work_score, min_coverage=min_coverage, max_quality_drop=max_quality_drop, allow_risk=allow_risk)
        if reason:
            item.update({"status": "skipped", "skip_reason": reason})
            results.append(item)
            skipped += 1
            continue
        old_book = _book(conn, int(candidate["old_book_id"]))
        new_book = _book(conn, int(candidate["new_book_id"]))
        if not old_book:
            item.update({"status": "skipped", "skip_reason": "old_book_id not found"})
            results.append(item)
            skipped += 1
            continue
        if not new_book:
            item.update({"status": "skipped", "skip_reason": "new_book_id not found"})
            results.append(item)
            skipped += 1
            continue
        if old_book.get("repo_area") != "library":
            item.update({"status": "skipped", "skip_reason": "old_book is not in library"})
            results.append(item)
            skipped += 1
            continue
        if new_book.get("repo_area") != "incoming":
            item.update({"status": "skipped", "skip_reason": "new_book is not in incoming"})
            results.append(item)
            skipped += 1
            continue
        old_source = Path(old_book["current_path"])
        new_source = Path(new_book["current_path"])
        if not old_source.exists():
            item.update({"status": "skipped", "skip_reason": "old_path missing", "old_source_path": str(old_source)})
            results.append(item)
            skipped += 1
            continue
        if not new_source.exists():
            item.update({"status": "skipped", "skip_reason": "new_path missing", "new_source_path": str(new_source)})
            results.append(item)
            skipped += 1
            continue
        plan = _candidate_plan(repo, candidate, old_book, new_book, ts)
        item.update(
            {
                "old_source_path": str(old_source),
                "new_source_path": str(new_source),
                **plan,
                "reason_summary": candidate.get("reason_summary"),
            }
        )
        planned += 1
        if dry_run:
            item["status"] = "dry_run"
            results.append(item)
            continue
        try:
            old_before, old_after = _move_verified(old_source, Path(plan["old_archive_path"]))
            new_before, new_after = _move_verified(new_source, Path(plan["new_library_path"]))
            now = now_ts()
            conn.execute("UPDATE books SET current_path = ?, repo_area = 'archive', status = 'archived', updated_at = ? WHERE id = ?", (plan["old_archive_path"], now, old_book["id"]))
            conn.execute("UPDATE books SET current_path = ?, repo_area = 'library', status = 'active', updated_at = ? WHERE id = ?", (plan["new_library_path"], now, new_book["id"]))
            group_note = _update_groups(conn, old_book["id"], new_book["id"], now)
            _operation(conn, repo, operation_type="apply_update_archive_old", book_id=old_book["id"], source_path=str(old_source), target_path=plan["old_archive_path"], before=old_before, after=old_after, status="success", report_path=str(report_path), reason=candidate.get("reason_summary") or "")
            _operation(conn, repo, operation_type="apply_update_promote_new", book_id=new_book["id"], source_path=str(new_source), target_path=plan["new_library_path"], before=new_before, after=new_after, status="success", report_path=str(report_path), reason=candidate.get("reason_summary") or "")
            conn.commit()
            item["status"] = "applied"
            if group_note:
                item["group_note"] = group_note
            applied += 1
        except Exception as exc:
            conn.rollback()
            item.update({"status": "failed", "fail_reason": str(exc)})
            failed += 1
        results.append(item)
    log = {
        "report_path": str(report_path),
        "dry_run": dry_run,
        "confirm": confirm,
        "total_candidates": len(candidates),
        "planned_count": planned,
        "applied_count": applied,
        "skipped_count": skipped,
        "failed_count": failed,
        "items": results,
    }
    log_path = repo / "logs" / f"apply_updates_{ts}.json"
    write_json(log_path, log)
    log["log_path"] = str(log_path)
    return log
