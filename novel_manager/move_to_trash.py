from __future__ import annotations

import sqlite3
import shutil
from pathlib import Path
from typing import Any

from .fingerprint import sha256_file
from .operations import log_operation
from .utils import file_ts, now_ts, write_json


def _book(conn: sqlite3.Connection, book_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    return dict(row) if row else None


def _unique_target(target: Path, ts: str) -> Path:
    if not target.exists():
        return target
    base = target.with_name(f"{target.stem}__trash_{ts}{target.suffix}")
    if not base.exists():
        return base
    for index in range(1, 10000):
        candidate = target.with_name(f"{target.stem}__trash_{ts}_{index}{target.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"cannot create unique trash target for {target}")


def move_book_to_trash(
    conn: sqlite3.Connection,
    repo: Path,
    book_id: int,
    *,
    dry_run: bool = False,
    confirm: bool = False,
    reason: str = "用户移入废弃区",
) -> dict[str, Any]:
    if dry_run and confirm:
        raise ValueError("--dry-run and --confirm cannot be used together")
    if not dry_run and not confirm:
        raise ValueError("use --dry-run or --confirm")
    ts = file_ts()
    result: dict[str, Any] = {
        "book_id": book_id,
        "dry_run": dry_run,
        "confirm": confirm,
        "status": "",
        "source_path": "",
        "target_path": "",
        "raw_sha256_before": None,
        "raw_sha256_after": None,
        "reason": reason,
    }
    book = _book(conn, book_id)
    if not book:
        result.update({"status": "failed", "error": "book_id 不存在"})
        return result
    source = Path(str(book.get("current_path") or ""))
    result["source_path"] = str(source)
    if not source.exists():
        result.update({"status": "failed", "error": "文件不存在"})
        return result
    trash_dir = repo / "trash"
    try:
        source.resolve().relative_to(trash_dir.resolve())
        result.update({"status": "failed", "error": "文件已经在废弃区"})
        return result
    except ValueError:
        pass
    target = _unique_target(trash_dir / source.name, ts)
    result["target_path"] = str(target)
    if dry_run:
        result["status"] = "dry_run"
        return result
    trash_dir.mkdir(parents=True, exist_ok=True)
    before = sha256_file(source)
    shutil.move(str(source), str(target))
    after = sha256_file(target)
    result["raw_sha256_before"] = before
    result["raw_sha256_after"] = after
    if before != after:
        result.update({"status": "failed", "error": "移动后 hash 校验失败"})
        return result
    now = now_ts()
    conn.execute(
        "UPDATE books SET current_path = ?, file_name = ?, repo_area = 'trash', status = 'trashed', updated_at = ? WHERE id = ?",
        (str(target), target.name, now, book_id),
    )
    log_operation(
        conn,
        repo,
        operation_type="move_to_trash",
        book_id=book_id,
        source_path=str(source),
        target_path=str(target),
        raw_sha256_before=before,
        raw_sha256_after=after,
        status="success",
        report_path=None,
        reason=reason,
    )
    result["status"] = "success"
    return result


def write_move_to_trash_log(repo: Path, result: dict[str, Any]) -> Path:
    log_dir = repo / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"move_to_trash_{file_ts()}.json"
    index = 1
    while path.exists():
        path = log_dir / f"move_to_trash_{file_ts()}_{index}.json"
        index += 1
    write_json(path, result)
    return path
