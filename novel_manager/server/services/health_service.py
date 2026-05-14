from __future__ import annotations

from pathlib import Path
from typing import Any

from ...db import connect as db_connect


def get_health_summary(repo_path: str) -> dict[str, Any]:
    """Get repository health summary."""
    root = Path(repo_path).expanduser().resolve()
    try:
        conn = db_connect(root)
    except Exception:
        return {
            "repo_path": str(root),
            "books": {"total": 0, "library": 0, "incoming": 0, "review_duplicates": 0, "archive": 0, "trash": 0},
            "pending": {"incoming_unprocessed": 0, "safe_new_books": 0, "safe_duplicates": 0, "update_candidates": 0, "manual_review": 0},
            "operations": {"recent_total": 0, "reversible": 0, "restored": 0, "failed": 0},
            "integrity": {"missing_files": 0, "path_area_mismatch": 0, "stale_incoming_records": 0, "dirty_file_names": 0},
            "status": "error",
            "warnings": ["无法连接数据库"],
            "errors": [],
        }

    try:
        books_stats = _count_books_by_area(conn)
        pending_stats = _count_pending_incoming(conn)
        ops_stats = _count_operations(conn)
        integrity_stats = _check_integrity(root, conn)

        warnings = []
        errors = []

        if integrity_stats["missing_files"] > 0:
            warnings.append(f"发现 {integrity_stats['missing_files']} 个缺失文件")
        if integrity_stats["path_area_mismatch"] > 0:
            warnings.append(f"发现 {integrity_stats['path_area_mismatch']} 个路径区域不一致")
        if integrity_stats["stale_incoming_records"] > 0:
            warnings.append(f"发现 {integrity_stats['stale_incoming_records']} 个 stale incoming 记录")

        status = "ok"
        if warnings:
            status = "warning"
        if integrity_stats["missing_files"] > 0 or integrity_stats["path_area_mismatch"] > 0:
            status = "warning"

        return {
            "repo_path": str(root),
            "books": books_stats,
            "pending": pending_stats,
            "operations": ops_stats,
            "integrity": integrity_stats,
            "status": status,
            "warnings": warnings,
            "errors": errors,
        }
    finally:
        conn.close()


def list_health_issues(repo_path: str) -> dict[str, Any]:
    """List detailed health issues."""
    root = Path(repo_path).expanduser().resolve()
    try:
        conn = db_connect(root)
    except Exception:
        return {"items": [{"severity": "error", "code": "db_connection_failed", "message": "无法连接数据库"}]}

    try:
        items = []

        path_issues = _check_book_paths(root, conn)
        items.extend(path_issues)

        stale_issues = _check_stale_incoming(root, conn)
        items.extend(stale_issues)

        ops_issues = _check_operation_records(root, conn)
        items.extend(ops_issues)

        return {"items": items}
    finally:
        conn.close()


def _count_books_by_area(conn) -> dict[str, int]:
    """Count books by repo_area."""
    total = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    library = conn.execute("SELECT COUNT(*) FROM books WHERE repo_area = 'library'").fetchone()[0]
    incoming = conn.execute("SELECT COUNT(*) FROM books WHERE repo_area = 'incoming'").fetchone()[0]
    review_duplicates = conn.execute("SELECT COUNT(*) FROM books WHERE repo_area = 'review_duplicates'").fetchone()[0]
    archive = conn.execute("SELECT COUNT(*) FROM books WHERE repo_area = 'archive'").fetchone()[0]
    trash = conn.execute("SELECT COUNT(*) FROM books WHERE repo_area = 'trash'").fetchone()[0]
    return {"total": total, "library": library, "incoming": incoming, "review_duplicates": review_duplicates, "archive": archive, "trash": trash}


def _count_pending_incoming(conn) -> dict[str, int]:
    """Count pending items in incoming area."""
    incoming_unprocessed = conn.execute("SELECT COUNT(*) FROM books WHERE repo_area = 'incoming'").fetchone()[0]

    safe_new_books = incoming_unprocessed

    safe_duplicates = 0
    try:
        safe_duplicates = conn.execute(
            "SELECT COUNT(*) FROM books a INNER JOIN books b ON a.raw_sha256 = b.raw_sha256 WHERE a.repo_area = 'incoming' AND b.repo_area = 'library' AND a.raw_sha256 IS NOT NULL AND a.raw_sha256 != ''"
        ).fetchone()[0]
    except Exception:
        pass

    update_candidates = 0
    try:
        update_candidates = conn.execute(
            "SELECT COUNT(*) FROM update_candidates WHERE recommendation = 'replace_recommended'"
        ).fetchone()[0]
    except Exception:
        pass

    manual_review = max(0, incoming_unprocessed - safe_duplicates - update_candidates)

    return {
        "incoming_unprocessed": incoming_unprocessed,
        "safe_new_books": safe_new_books,
        "safe_duplicates": safe_duplicates,
        "update_candidates": update_candidates,
        "manual_review": manual_review,
    }


def _count_operations(conn) -> dict[str, int]:
    """Count operation records."""
    try:
        total = conn.execute("SELECT COUNT(*) FROM web_operation_records").fetchone()[0]
        reversible = conn.execute("SELECT COUNT(*) FROM web_operation_records WHERE reversible = 1").fetchone()[0]
        restored = conn.execute("SELECT COUNT(*) FROM web_operation_records WHERE restored = 1").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM web_operation_records WHERE status != 'success'").fetchone()[0]
        return {"recent_total": total, "reversible": reversible, "restored": restored, "failed": failed}
    except Exception:
        return {"recent_total": 0, "reversible": 0, "restored": 0, "failed": 0}


def _check_integrity(root: Path, conn) -> dict[str, int]:
    """Check repository integrity."""
    missing_files = 0
    path_area_mismatch = 0
    stale_incoming_records = 0
    dirty_file_names = 0

    books = conn.execute("SELECT id, repo_area, current_path, file_name FROM books").fetchall()
    for book in books:
        current_path = book["current_path"]
        repo_area = book["repo_area"]

        if current_path:
            try:
                p = Path(current_path)
                if not p.exists():
                    missing_files += 1
                else:
                    expected_area = _get_expected_area(root, p)
                    if expected_area and repo_area != expected_area:
                        path_area_mismatch += 1
            except Exception:
                missing_files += 1

        if repo_area == "incoming":
            if not current_path or not _is_path_in_area(root, current_path, "incoming"):
                stale_incoming_records += 1

    return {
        "missing_files": missing_files,
        "path_area_mismatch": path_area_mismatch,
        "stale_incoming_records": stale_incoming_records,
        "dirty_file_names": dirty_file_names,
    }


def _check_book_paths(root: Path, conn) -> list[dict]:
    """Check book path consistency."""
    items = []
    books = conn.execute("SELECT id, repo_area, current_path, file_name FROM books").fetchall()

    for book in books:
        current_path = book["current_path"]
        repo_area = book["repo_area"]
        file_name = book["file_name"] or ""

        if not current_path:
            items.append({
                "severity": "warning",
                "code": "missing_path",
                "book_id": book["id"],
                "file_name": file_name,
                "repo_area": repo_area,
                "current_path": "",
                "message": "数据库记录缺少文件路径。",
            })
            continue

        try:
            p = Path(current_path)
            if not p.exists():
                items.append({
                    "severity": "error",
                    "code": "missing_file",
                    "book_id": book["id"],
                    "file_name": file_name,
                    "repo_area": repo_area,
                    "current_path": current_path,
                    "message": f"文件不存在：{current_path}",
                })
            else:
                expected_area = _get_expected_area(root, p)
                if expected_area and repo_area != expected_area:
                    items.append({
                        "severity": "warning",
                        "code": "path_area_mismatch",
                        "book_id": book["id"],
                        "file_name": file_name,
                        "repo_area": repo_area,
                        "current_path": current_path,
                        "message": f"数据库区域为 {repo_area}，但文件路径不在 {repo_area} 目录下。",
                    })
        except Exception:
            items.append({
                "severity": "error",
                "code": "invalid_path",
                "book_id": book["id"],
                "file_name": file_name,
                "repo_area": repo_area,
                "current_path": current_path,
                "message": f"路径无效：{current_path}",
            })

    return items


def _check_stale_incoming(root: Path, conn) -> list[dict]:
    """Check stale incoming records."""
    items = []
    books = conn.execute("SELECT id, current_path, file_name FROM books WHERE repo_area = 'incoming'").fetchall()

    for book in books:
        current_path = book["current_path"]
        file_name = book["file_name"] or ""

        if not current_path or not _is_path_in_area(root, current_path, "incoming"):
            items.append({
                "severity": "warning",
                "code": "stale_incoming_record",
                "book_id": book["id"],
                "file_name": file_name,
                "repo_area": "incoming",
                "current_path": current_path or "",
                "message": "incoming 记录的文件路径不在 incoming 目录下。",
            })

    return items


def _check_operation_records(root: Path, conn) -> list[dict]:
    """Check operation records for issues."""
    items = []
    try:
        ops = conn.execute(
            "SELECT operation_id, operation_type, reversible, restored, target_path FROM web_operation_records WHERE reversible = 1 AND restored = 0",
        ).fetchall()

        for op in ops:
            target_path = op["target_path"]
            if target_path:
                try:
                    if not Path(target_path).exists():
                        items.append({
                            "severity": "warning",
                            "code": "restore_target_missing",
                            "book_id": None,
                            "file_name": "",
                            "repo_area": "",
                            "current_path": target_path,
                            "message": f"可恢复操作 {op['operation_id']} 的目标文件不存在：{target_path}",
                        })
                except Exception:
                    pass
    except Exception:
        pass

    return items


def _get_expected_area(root: Path, file_path: Path) -> str | None:
    """Determine expected repo_area from file path."""
    try:
        resolved = file_path.resolve()
        root_resolved = root.resolve()

        rel = resolved.relative_to(root_resolved)
        parts = rel.parts

        if not parts:
            return None

        first = parts[0]
        if first == "library":
            return "library"
        elif first == "incoming":
            return "incoming"
        elif first == "review_duplicates":
            return "review_duplicates"
        elif first == "archive":
            return "archive"
        elif first == "trash":
            return "trash"
        elif first == "quarantine":
            return "quarantine"

        return None
    except ValueError:
        return None


def _is_path_in_area(root: Path, path_str: str, area: str) -> bool:
    """Check if path is within specified area."""
    try:
        p = Path(path_str).resolve()
        area_dir = (root / area).resolve()
        p.relative_to(area_dir)
        return True
    except ValueError:
        return False
    except Exception:
        return False