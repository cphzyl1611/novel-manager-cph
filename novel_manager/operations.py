from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .fingerprint import sha256_file
from .utils import ensure_dir, file_ts, now_ts, read_json, write_json


COMMON_MOJIBAKE_FIXES = {
    "楂樿川閲?": "高质量",
    "楂樿川閲�": "高质量",
    "浣庤川閲?": "低质量",
    "浣庤川閲�": "低质量",
    "绔犺妭寮傚父": "章节异常",
    "鐤戜技缂虹珷": "疑似缺章",
    "鐤戜技涔辩爜": "疑似乱码",
    "骞垮憡杈冨": "广告较多",
    "寰呮暣鐞?": "待整理",
    "寰呮暣鐞�": "待整理",
}


def clean_log_text(value: str | None) -> str:
    text = "" if value is None else str(value)
    for bad, good in COMMON_MOJIBAKE_FIXES.items():
        text = text.replace(bad, good)
    return text


def unique_target_path(target_path: Path) -> Path:
    if not target_path.exists():
        return target_path
    stem = target_path.stem
    suffix = target_path.suffix
    parent = target_path.parent
    index = 1
    while True:
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _append_operation_log(repo: Path, record: dict[str, Any]) -> None:
    log_path = repo / "logs" / "operations.log"
    ensure_dir(log_path.parent)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_operation(
    conn: sqlite3.Connection,
    repo: Path,
    *,
    operation_type: str,
    book_id: int | None,
    source_path: str,
    target_path: str,
    raw_sha256_before: str | None,
    raw_sha256_after: str | None,
    status: str,
    report_path: str | None,
    reason: str,
) -> None:
    created_at = now_ts()
    reason = clean_log_text(reason)
    conn.execute(
        """
        INSERT INTO operations
        (operation_type, book_id, source_path, target_path, raw_sha256_before, raw_sha256_after,
         status, report_path, reason, created_at, applied_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            operation_type,
            book_id,
            source_path,
            target_path,
            raw_sha256_before,
            raw_sha256_after,
            status,
            report_path,
            reason,
            created_at,
            created_at if status in {"success", "failed"} else None,
        ),
    )
    conn.commit()
    record = {
        "operation_type": operation_type,
        "book_id": book_id,
        "source_path": source_path,
        "target_path": target_path,
        "raw_sha256_before": raw_sha256_before,
        "raw_sha256_after": raw_sha256_after,
        "status": status,
        "report_path": report_path,
        "reason": reason,
        "created_at": created_at,
    }
    _append_operation_log(repo, record)


def safe_move_file(
    conn: sqlite3.Connection,
    repo: Path,
    source: Path,
    target_dir: Path,
    reason: str,
    *,
    book_id: int | None = None,
    report_path: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    ensure_dir(target_dir)
    target = unique_target_path(target_dir / source.name)
    plan = {"source_path": str(source), "target_path": str(target), "book_id": book_id, "reason": reason}
    if dry_run:
        return {"status": "dry_run", **plan}
    before = None
    after = None
    try:
        before = sha256_file(source)
        shutil.move(str(source), str(target))
        after = sha256_file(target)
        status = "success" if before == after else "failed"
        if status == "success" and book_id is not None:
            conn.execute(
                "UPDATE books SET current_path = ?, repo_area = ?, status = ?, updated_at = ? WHERE id = ?",
                (str(target), "review_duplicates", "active", now_ts(), book_id),
            )
            conn.commit()
        log_operation(
            conn,
            repo,
            operation_type="stage_duplicate",
            book_id=book_id,
            source_path=str(source),
            target_path=str(target),
            raw_sha256_before=before,
            raw_sha256_after=after,
            status=status,
            report_path=report_path,
            reason=reason,
        )
        return {"status": status, "raw_sha256_before": before, "raw_sha256_after": after, **plan}
    except Exception as exc:
        log_operation(
            conn,
            repo,
            operation_type="stage_duplicate",
            book_id=book_id,
            source_path=str(source),
            target_path=str(target),
            raw_sha256_before=before,
            raw_sha256_after=after,
            status="failed",
            report_path=report_path,
            reason=f"{reason}; error={exc}",
        )
        return {"status": "failed", "error": str(exc), **plan}


def stage_duplicates_from_report(
    conn: sqlite3.Connection,
    repo: Path,
    report: Path,
    *,
    dry_run: bool,
) -> tuple[list[dict[str, Any]], Path | None]:
    report_path = report if report.is_absolute() else repo / report
    payload = read_json(report_path)
    results: list[dict[str, Any]] = []
    for group in payload.get("groups", []):
        for member in group.get("members", []):
            role = member.get("suggested_role")
            if role not in {"archive_candidate", "review"}:
                continue
            book = member.get("book") or {}
            source = Path(book.get("current_path") or "")
            if not source.exists():
                results.append(
                    {
                        "status": "failed",
                        "book_id": book.get("id"),
                        "source_path": str(source),
                        "error": "source file does not exist",
                    }
                )
                continue
            results.append(
                safe_move_file(
                    conn,
                    repo,
                    source,
                    repo / "review_duplicates",
                    member.get("reason") or "duplicate candidate",
                    book_id=book.get("id"),
                    report_path=str(report_path),
                    dry_run=dry_run,
                )
            )
    apply_log = None
    if not dry_run:
        apply_log = repo / "logs" / f"stage_duplicates_apply_{file_ts()}.json"
        write_json(apply_log, {"report_path": str(report_path), "results": results})
    return results, apply_log
