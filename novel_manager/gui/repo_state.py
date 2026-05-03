from __future__ import annotations

import json
import os
import platform
import subprocess
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .i18n import area_label
from .report_loaders import parse_operation_line

CONFIG_PATH = Path.home() / ".novel_repo_manager_gui.json"
REPORT_TYPES = {
    "duplicate": "reports/duplicate",
    "quality": "reports/quality",
    "errors": "reports/errors",
    "summary": "reports/summary",
    "diagnostic": "reports/diagnostic",
    "update": "reports/update",
    "group": "reports/group",
    "rename": "reports/rename",
    "health": "reports/health",
}


def load_gui_settings() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_gui_settings(settings: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def get_db_path(repo: str | Path) -> Path:
    return Path(repo) / "db" / "novel_repo.sqlite"


def get_repo_structure_status(repo: str | Path) -> dict[str, Any]:
    root = Path(repo)
    required = ["db", "config", "library", "reports"]
    status = {name: (root / name).exists() for name in required}
    txt_count = len(list(root.glob("*.txt"))) if root.exists() and root.is_dir() else 0
    initialized = root.exists() and all(status.values())
    return {
        "path": str(root),
        "exists": root.exists(),
        "is_dir": root.is_dir(),
        "initialized": initialized,
        "missing": [name for name, ok in status.items() if not ok],
        "parts": status,
        "txt_count": txt_count,
        "kind": "initialized_repo" if initialized else ("plain_txt_folder" if txt_count > 0 else "incomplete_or_empty"),
    }


def is_initialized_repo(repo_path: str | Path) -> bool:
    return bool(get_repo_structure_status(repo_path)["initialized"])


def detect_plain_txt_folder(path: str | Path) -> dict[str, Any]:
    root = Path(path)
    files = sorted(root.glob("*.txt")) if root.exists() and root.is_dir() else []
    return {"path": str(root), "exists": root.exists(), "txt_count": len(files), "files": [str(p) for p in files[:200]], "is_plain_txt_folder": len(files) > 0 and not is_initialized_repo(root)}


def unique_copy_target(target: Path) -> Path:
    if not target.exists():
        return target
    for index in range(1, 10000):
        candidate = target.with_name(f"{target.stem}_{index}{target.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"cannot create unique target for {target}")


def import_txt_folder_to_library(source_folder: str | Path, repo_path: str | Path, *, dry_run: bool = True, apply: bool = False) -> dict[str, Any]:
    import shutil

    if dry_run and apply:
        raise ValueError("dry_run and apply cannot both be true")
    source = Path(source_folder)
    repo = Path(repo_path)
    library = repo / "library"
    files = sorted(path for path in source.glob("*.txt") if path.is_file()) if source.exists() else []
    items: list[dict[str, Any]] = []
    copied = 0
    for path in files:
        target = unique_copy_target(library / path.name)
        item = {"source": str(path), "target": str(target), "conflict": target.name != path.name, "status": "dry_run" if dry_run else "pending"}
        if apply:
            library.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            item["status"] = "copied"
            copied += 1
        items.append(item)
    return {"dry_run": dry_run, "apply": apply, "found_count": len(files), "copied_count": copied, "items": items}


def _connect(repo: str | Path) -> sqlite3.Connection | None:
    db = get_db_path(repo)
    if not db.exists():
        return None
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def _count(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    try:
        return int(conn.execute(sql, params).fetchone()[0] or 0)
    except sqlite3.Error:
        return 0


def load_dashboard_stats(repo: str | Path) -> dict[str, int]:
    conn = _connect(repo)
    stats = {
        "books": 0,
        "work_groups": 0,
        "duplicate_groups": 0,
        "near_duplicates": 0,
        "update_candidates": 0,
        "todo_books": 0,
    }
    if conn is None:
        return stats
    try:
        stats["books"] = _count(conn, "SELECT COUNT(*) FROM books")
        stats["work_groups"] = _count(conn, "SELECT COUNT(*) FROM work_groups")
        stats["duplicate_groups"] = _count(conn, "SELECT COUNT(*) FROM duplicate_groups")
        stats["near_duplicates"] = _count(conn, "SELECT COUNT(*) FROM duplicate_groups WHERE group_type = 'near_duplicate'")
        stats["update_candidates"] = _count(conn, "SELECT COUNT(*) FROM update_candidates")
        stats["todo_books"] = _count(
            conn,
            """
            SELECT COUNT(DISTINCT b.id)
            FROM books b
            JOIN book_tags bt ON bt.book_id = b.id
            JOIN tags t ON t.id = bt.tag_id
            WHERE t.name IN ('待整理', '寰呮暣鐞?')
            """,
        )
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return stats


def load_books(repo: str | Path, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    filters = filters or {}
    conn = _connect(repo)
    if conn is None:
        return []
    clauses = ["1=1"]
    params: list[Any] = []
    area = filters.get("area", "all")
    if area and area != "all":
        clauses.append("b.repo_area = ?")
        params.append(area)
    query = filters.get("query")
    if query:
        like = f"%{query}%"
        clauses.append("(b.file_name LIKE ? OR b.title_norm LIKE ? OR b.author_norm LIKE ? OR b.current_path LIKE ?)")
        params.extend([like, like, like, like])
    status = filters.get("status")
    if status and status != "all":
        clauses.append("COALESCE(b.reading_status, '') = ?")
        params.append(status)
    if filters.get("problem_only"):
        clauses.append(
            "(b.ad_line_count > 0 OR b.mojibake_rate > 0 OR b.duplicate_chapter_count > 0 "
            "OR b.missing_chapter_count > 0 OR b.chapter_order_error_count > 0 OR b.truncated_risk = 1)"
        )
    min_quality = filters.get("min_quality")
    max_quality = filters.get("max_quality")
    if min_quality not in (None, ""):
        clauses.append("COALESCE(b.quality_score, 0) >= ?")
        params.append(float(min_quality))
    if max_quality not in (None, ""):
        clauses.append("COALESCE(b.quality_score, 0) <= ?")
        params.append(float(max_quality))
    tag = filters.get("tag")
    tag_join = ""
    if tag:
        tag_join = "JOIN book_tags fbt ON fbt.book_id = b.id JOIN tags ft ON ft.id = fbt.tag_id"
        clauses.append("ft.name = ?")
        params.append(tag)
    limit = int(filters.get("limit") or 200)
    sql = f"""
        SELECT b.*,
               GROUP_CONCAT(t.name, ', ') AS tags
        FROM books b
        LEFT JOIN book_tags bt ON bt.book_id = b.id
        LEFT JOIN tags t ON t.id = bt.tag_id
        {tag_join}
        WHERE {' AND '.join(f'({c})' for c in clauses)}
        GROUP BY b.id
        ORDER BY b.updated_at DESC, b.id DESC
        LIMIT ?
    """
    params.append(limit)
    try:
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        for row in rows:
            row["repo_area_label"] = area_label(row.get("repo_area"))
        return rows
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def load_groups(repo: str | Path, limit: int = 200) -> list[dict[str, Any]]:
    conn = _connect(repo)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT wg.*, COUNT(bgm.book_id) AS member_count
            FROM work_groups wg
            LEFT JOIN book_group_members bgm ON bgm.work_group_id = wg.id
            GROUP BY wg.id
            ORDER BY wg.updated_at DESC, wg.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def load_group_members(repo: str | Path, group_id: int) -> list[dict[str, Any]]:
    conn = _connect(repo)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT bgm.book_id, bgm.role, bgm.confidence, bgm.source,
                   b.file_name, b.current_path, b.repo_area, b.quality_score,
                   b.quality_level, b.chapter_count, b.char_count_clean
            FROM book_group_members bgm
            JOIN books b ON b.id = bgm.book_id
            WHERE bgm.work_group_id = ?
            ORDER BY bgm.role = 'primary' DESC, b.quality_score DESC
            """,
            (group_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def load_reports(repo: str | Path, report_type: str = "all", limit: int = 200) -> list[dict[str, Any]]:
    root = Path(repo)
    types = REPORT_TYPES if report_type == "all" else {report_type: REPORT_TYPES.get(report_type, "")}
    entries: list[dict[str, Any]] = []
    for item_type, relative in types.items():
        if not relative:
            continue
        directory = root / relative
        if not directory.exists():
            continue
        for path in directory.iterdir():
            if not path.is_file():
                continue
            entries.append(
                {
                    "report_type": item_type,
                    "file_name": path.name,
                    "suffix": path.suffix.lstrip(".").lower(),
                    "size": path.stat().st_size,
                    "modified_time": _mtime(path),
                    "mtime": path.stat().st_mtime,
                    "path": str(path),
                }
            )
    entries.sort(key=lambda item: item["mtime"], reverse=True)
    return entries[:limit]


def load_recent_operations(repo: str | Path, limit: int = 50) -> list[str]:
    log_path = Path(repo) / "logs" / "operations.log"
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return [parse_operation_line(line).get("summary", "历史日志记录") for line in lines[-limit:]]
    except OSError:
        return []


def load_recent_operation_records(repo: str | Path, limit: int = 50) -> list[dict[str, Any]]:
    log_path = Path(repo) / "logs" / "operations.log"
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    records = [parse_operation_line(line) for line in lines[-limit:]]
    records.reverse()
    for record in records:
        record["log_path"] = str(log_path)
    return records


def open_in_system(path: str | Path) -> tuple[bool, str]:
    target = Path(path)
    try:
        os.startfile(str(target))  # type: ignore[attr-defined]
        return True, str(target)
    except Exception as exc:
        return False, f"{target} ({exc})"


def open_file(path: str | Path) -> tuple[bool, str]:
    target = Path(path)
    if not target.exists():
        return False, f"文件不存在：{target}"
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.run(["open", str(target)], check=False)
        else:
            subprocess.run(["xdg-open", str(target)], check=False)
        return True, str(target)
    except Exception as exc:
        return False, f"{target} ({exc})"


def open_parent_folder(path: str | Path, *, select_file: bool = True) -> tuple[bool, str]:
    target = Path(path)
    if not target.exists():
        return False, f"路径不存在：{target}"
    try:
        system = platform.system()
        if system == "Windows" and select_file:
            subprocess.run(["explorer", "/select,", str(target)], check=False)
        elif system == "Windows":
            os.startfile(str(target.parent if target.is_file() else target))  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.run(["open", str(target.parent if target.is_file() else target)], check=False)
        else:
            subprocess.run(["xdg-open", str(target.parent if target.is_file() else target)], check=False)
        return True, str(target)
    except Exception as exc:
        return False, f"{target} ({exc})"
