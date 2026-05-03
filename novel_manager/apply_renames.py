from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .fingerprint import sha256_file
from .operations import log_operation
from .utils import file_ts, now_ts, read_json, write_json

BLOCKED_RISKS = {
    "target_name_conflict",
    "manual_review_needed",
    "title_missing",
    "author_suspicious",
    "target_truncated",
    "windows_reserved_name",
    "unsafe_target",
    "low_quality_book",
    "mojibake_risk",
}


def _resolve_report_path(repo: Path, report: Path) -> Path:
    if report.is_absolute() or report.exists():
        return report
    return repo / report


def _unique_log_path(repo: Path, ts: str) -> Path:
    log_dir = repo / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"apply_renames_{ts}.json"
    if not path.exists():
        return path
    for index in range(1, 10000):
        candidate = log_dir / f"apply_renames_{ts}_{index}.json"
        if not candidate.exists():
            return candidate
    raise FileExistsError("could not create unique apply_renames log path")


def _book(conn: sqlite3.Connection, book_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    return dict(row) if row else None


def _suggestions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("suggestions")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _skip_reason(
    suggestion: dict[str, Any],
    *,
    allow_duplicate_book_group: bool,
    allow_author_missing: bool,
) -> str | None:
    action = suggestion.get("action")
    if action != "rename_recommended":
        return f"action is not rename_recommended: {action}"
    target = str(suggestion.get("target_file_name") or "").strip()
    if not target:
        return "target_file_name is empty"
    current = str(suggestion.get("current_file_name") or "").strip()
    if target == current:
        return "target_file_name equals current_file_name"
    risks = set(suggestion.get("risk_flags") or [])
    blocked = risks & BLOCKED_RISKS
    if blocked:
        return "blocked risk flags: " + ",".join(sorted(blocked))
    if "duplicate_book_group" in risks and not allow_duplicate_book_group:
        return "duplicate_book_group risk"
    if "author_missing" in risks and not allow_author_missing:
        return "author_missing risk"
    return None


def _same_directory(source: Path, target: Path) -> bool:
    try:
        return source.parent.resolve() == target.parent.resolve()
    except OSError:
        return source.parent.absolute() == target.parent.absolute()


def _item_base(suggestion: dict[str, Any]) -> dict[str, Any]:
    return {
        "book_id": suggestion.get("book_id"),
        "current_path": suggestion.get("current_path"),
        "target_path": suggestion.get("target_path_preview"),
        "current_file_name": suggestion.get("current_file_name"),
        "target_file_name": suggestion.get("target_file_name"),
        "action": suggestion.get("action"),
        "risk_flags": suggestion.get("risk_flags") or [],
        "raw_sha256_before": None,
        "raw_sha256_after": None,
    }


def apply_renames_from_report(
    conn: sqlite3.Connection,
    repo: Path,
    report: Path,
    *,
    dry_run: bool = False,
    confirm: bool = False,
    limit: int | None = None,
    allow_duplicate_book_group: bool = False,
    allow_author_missing: bool = True,
) -> dict[str, Any]:
    if dry_run and confirm:
        raise ValueError("--dry-run and --confirm cannot be used together")
    if not dry_run and not confirm:
        raise ValueError("use dry_run=True or confirm=True")

    report_path = _resolve_report_path(repo, report)
    payload = read_json(report_path)
    suggestions = _suggestions(payload)
    ts = file_ts()

    items: list[dict[str, Any]] = []
    planned = 0
    renamed = 0
    skipped = 0
    failed = 0

    for suggestion in suggestions:
        if limit is not None and planned >= limit:
            break

        item = _item_base(suggestion)
        skip = _skip_reason(
            suggestion,
            allow_duplicate_book_group=allow_duplicate_book_group,
            allow_author_missing=allow_author_missing,
        )
        if skip:
            item.update({"status": "skipped", "skip_reason": skip})
            items.append(item)
            skipped += 1
            continue

        book_id = suggestion.get("book_id")
        try:
            book_id_int = int(book_id)
        except (TypeError, ValueError):
            item.update({"status": "skipped", "skip_reason": "book_id is invalid"})
            items.append(item)
            skipped += 1
            continue

        book = _book(conn, book_id_int)
        if not book:
            item.update({"status": "skipped", "skip_reason": "book_id not found"})
            items.append(item)
            skipped += 1
            continue

        source = Path(str(book.get("current_path") or ""))
        try:
            target = source.with_name(str(suggestion.get("target_file_name") or "").strip())
        except ValueError:
            item.update({"status": "skipped", "skip_reason": "target_file_name is not a plain file name"})
            items.append(item)
            skipped += 1
            continue
        item.update({"current_path": str(source), "target_path": str(target)})

        if not source.exists():
            item.update({"status": "skipped", "skip_reason": "current_path does not exist"})
            items.append(item)
            skipped += 1
            continue
        if target.exists():
            item.update({"status": "skipped", "skip_reason": "target_path already exists"})
            items.append(item)
            skipped += 1
            continue
        if source.name == target.name:
            item.update({"status": "skipped", "skip_reason": "target_file_name equals current_file_name"})
            items.append(item)
            skipped += 1
            continue
        if not _same_directory(source, target):
            item.update({"status": "skipped", "skip_reason": "target_path is not in the same directory"})
            items.append(item)
            skipped += 1
            continue

        planned += 1
        if dry_run:
            item.update({"status": "dry_run", "reason_summary": suggestion.get("reason_summary")})
            items.append(item)
            continue

        before = None
        after = None
        try:
            before = sha256_file(source)
            source.rename(target)
            after = sha256_file(target)
            item["raw_sha256_before"] = before
            item["raw_sha256_after"] = after
            if before != after:
                item.update({"status": "failed", "fail_reason": "hash mismatch after rename"})
                failed += 1
                items.append(item)
                continue
            now = now_ts()
            conn.execute(
                "UPDATE books SET current_path = ?, file_name = ?, updated_at = ? WHERE id = ?",
                (str(target), target.name, now, book_id_int),
            )
            log_operation(
                conn,
                repo,
                operation_type="apply_rename",
                book_id=book_id_int,
                source_path=str(source),
                target_path=str(target),
                raw_sha256_before=before,
                raw_sha256_after=after,
                status="success",
                report_path=str(report_path),
                reason=suggestion.get("reason_summary") or "rename_recommended",
            )
            item.update({"status": "renamed", "reason_summary": suggestion.get("reason_summary")})
            renamed += 1
        except Exception as exc:
            conn.rollback()
            item.update(
                {
                    "status": "failed",
                    "fail_reason": str(exc),
                    "raw_sha256_before": before,
                    "raw_sha256_after": after,
                }
            )
            failed += 1
        items.append(item)

    log = {
        "report_path": str(report_path),
        "dry_run": dry_run,
        "confirm": confirm,
        "total_suggestions": len(suggestions),
        "planned_count": planned,
        "renamed_count": renamed,
        "skipped_count": skipped,
        "failed_count": failed,
        "items": items,
    }
    log_path = _unique_log_path(repo, ts)
    write_json(log_path, log)
    log["log_path"] = str(log_path)
    return log
