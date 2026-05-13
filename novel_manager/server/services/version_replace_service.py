from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from ...db import connect as db_connect
from ...utils import ensure_dir, now_ts
from .operation_service import _ensure_table, _write_log
from .progress_service import copy_reading_progress_for_replacement


def _get_book(conn, book_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    return dict(row) if row else None


def _resolve_and_check(repo: Path, rel_or_abs: str) -> Path | None:
    """Resolve path and verify it's inside repo."""
    try:
        p = Path(rel_or_abs)
        if not p.is_absolute():
            p = repo / p
        p = p.resolve()
        try:
            p.relative_to(repo.resolve())
        except ValueError:
            return None
        return p
    except Exception:
        return None


def _unique_target(dest_dir: Path, source: Path) -> Path:
    """Generate unique target path, never overwrite."""
    ensure_dir(dest_dir)
    target = dest_dir / source.name
    if not target.exists():
        return target
    stem = target.stem
    tag = now_ts().replace(" ", "_").replace(":", "")
    for n in range(200):
        suffix = f"__{tag}" + (f"_{n}" if n else "")
        candidate = dest_dir / f"{stem}{suffix}{source.suffix}"
        if not candidate.exists():
            return candidate
    raise OSError("无法生成唯一目标文件名")


def replace_library_version(repo_path: str, incoming_book_id: int, matched_book_id: int) -> dict[str, Any]:
    """Safely replace library version with incoming version."""
    root = Path(repo_path).expanduser().resolve()
    try:
        conn = db_connect(root)
    except Exception:
        return {"ok": False, "error": "无法连接数据库"}

    try:
        incoming_book = _get_book(conn, incoming_book_id)
        if incoming_book is None:
            return {"ok": False, "error_code": "book_not_found", "error": "新下载小说不存在", "debug": {"book_id": incoming_book_id}}

        incoming_area = incoming_book.get("repo_area", "")
        incoming_path_str = incoming_book.get("current_path", "")
        incoming_path_exists = Path(incoming_path_str).exists() if incoming_path_str else False

        if incoming_area != "incoming":
            return {
                "ok": False,
                "error_code": "incoming_item_stale",
                "error": "该文件已不在新下载区，可能已经被处理。请刷新检测结果。",
                "debug": {"book_id": incoming_book_id, "current_repo_area": incoming_area, "current_path": incoming_path_str, "path_exists": incoming_path_exists},
            }

        matched_book = _get_book(conn, matched_book_id)
        if matched_book is None:
            return {"ok": False, "error_code": "book_not_found", "error": "匹配的小说不存在", "debug": {"book_id": matched_book_id}}

        matched_area = matched_book.get("repo_area", "")
        if matched_area != "library":
            return {
                "ok": False,
                "error_code": "matched_not_in_library",
                "error": "匹配的小说已不在书架中，无法替换。请刷新检测结果。",
                "debug": {"book_id": matched_book_id, "current_repo_area": matched_area},
            }

        incoming_path = _resolve_and_check(root, incoming_path_str)
        if incoming_path is None or not incoming_path.exists():
            return {
                "ok": False,
                "error_code": "incoming_file_missing",
                "error": "新下载文件不存在或路径不合法",
                "debug": {"book_id": incoming_book_id, "current_repo_area": incoming_area, "current_path": incoming_path_str, "path_exists": incoming_path_exists},
            }

        matched_path = _resolve_and_check(root, matched_book.get("current_path", ""))
        if matched_path is None or not matched_path.exists():
            return {"ok": False, "error": "旧版文件不存在或路径不合法"}

        archive_dir = root / "archive" / "replaced"
        library_dir = root / "library"

        old_archive_target = _unique_target(archive_dir, matched_path)
        new_library_target = _unique_target(library_dir, incoming_path)

        shutil.move(str(matched_path), str(old_archive_target))

        try:
            shutil.move(str(incoming_path), str(new_library_target))
        except Exception as e:
            try:
                shutil.move(str(old_archive_target), str(matched_path))
            except Exception:
                pass
            return {"ok": False, "error": f"移动新版失败: {e}"}

        now = now_ts()
        conn.execute(
            "UPDATE books SET repo_area = ?, current_path = ?, file_name = ?, status = ?, updated_at = ? WHERE id = ?",
            ("archive", str(old_archive_target), old_archive_target.name, "replaced_old", now, matched_book_id),
        )
        conn.execute(
            "UPDATE books SET repo_area = ?, current_path = ?, file_name = ?, status = ?, updated_at = ? WHERE id = ?",
            ("library", str(new_library_target), new_library_target.name, "normal", now, incoming_book_id),
        )

        op_id = str(uuid.uuid4())[:12]

        progress_result = copy_reading_progress_for_replacement(conn, matched_book_id, incoming_book_id)

        detail = {
            "incoming_book_id": incoming_book_id,
            "matched_book_id": matched_book_id,
            "old_original_path": str(matched_path),
            "old_archive_path": str(old_archive_target),
            "new_original_path": str(incoming_path),
            "new_library_path": str(new_library_target),
            "progress_transfer": {
                "from_book_id": matched_book_id,
                "to_book_id": incoming_book_id,
                "copied": progress_result["copied"],
                "skipped": progress_result["skipped"],
                "devices": progress_result["devices"],
            },
        }
        conn.execute(
            """INSERT INTO web_operation_records (operation_id, operation_type, book_id, title, file_name, source_path, target_path, source_area, target_area, status, reversible, restored, created_at, detail_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'success', 1, 0, ?, ?)""",
            (op_id, "replace_library_version", incoming_book_id, incoming_book.get("title_norm") or incoming_book.get("title_raw") or incoming_book.get("file_name", ""),
             new_library_target.name, str(incoming_path), str(new_library_target), "incoming", "library", now, json.dumps(detail, ensure_ascii=False)),
        )
        conn.commit()

        progress_msg = f" progress_copied={progress_result['copied']}" if progress_result["copied"] > 0 else ""
        _write_log(root, f"replace_library_version incoming_id={incoming_book_id} matched_id={matched_book_id} old={matched_path}→{old_archive_target} new={incoming_path}→{new_library_target} op_id={op_id}{progress_msg}")

        message = "已将新版加入书架，旧版已归档"
        if progress_result["copied"] > 0:
            message += "，新版已继承旧版阅读进度"

        return {
            "ok": True,
            "action": "replace_library_version",
            "incoming_book_id": incoming_book_id,
            "matched_book_id": matched_book_id,
            "old_book_archived_path": str(old_archive_target),
            "new_book_library_path": str(new_library_target),
            "operation_id": op_id,
            "progress_transfer": progress_result,
            "message": message,
        }
    finally:
        conn.close()


def restore_replace_library_version(repo_path: str, operation_id: str) -> dict[str, Any]:
    """Restore a replace_library_version operation."""
    root = Path(repo_path).expanduser().resolve()
    try:
        conn = _ensure_table(root)
    except Exception:
        return {"ok": False, "error": "无法连接数据库"}

    try:
        row = conn.execute("SELECT * FROM web_operation_records WHERE operation_id = ?", (operation_id,)).fetchone()
        if row is None:
            return {"ok": False, "error": "操作记录不存在"}
        rec = dict(row)

        if not rec.get("reversible"):
            return {"ok": False, "error": "该操作不可恢复"}
        if rec.get("restored"):
            return {"ok": False, "error": "该操作已经恢复过，不能重复恢复"}
        if rec.get("operation_type") != "replace_library_version":
            return {"ok": False, "error": "该操作类型不支持此恢复方式"}

        detail_str = rec.get("detail_json")
        if not detail_str:
            return {"ok": False, "error": "操作详情缺失"}
        try:
            detail = json.loads(detail_str)
        except json.JSONDecodeError:
            return {"ok": False, "error": "操作详情解析失败"}

        incoming_book_id = detail.get("incoming_book_id")
        matched_book_id = detail.get("matched_book_id")
        old_archive_path = detail.get("old_archive_path")
        new_library_path = detail.get("new_library_path")

        if not all([incoming_book_id, matched_book_id, old_archive_path, new_library_path]):
            return {"ok": False, "error": "操作详情不完整"}

        old_archive = Path(old_archive_path)
        new_library = Path(new_library_path)

        if not old_archive.exists():
            return {"ok": False, "error": "当前文件位置已变化，无法自动恢复。请手动检查文件。"}
        if not new_library.exists():
            return {"ok": False, "error": "当前文件位置已变化，无法自动恢复。请手动检查文件。"}

        incoming_book = _get_book(conn, incoming_book_id)
        matched_book = _get_book(conn, matched_book_id)

        if incoming_book is None or matched_book is None:
            return {"ok": False, "error": "相关书籍记录不存在"}

        if incoming_book.get("repo_area") != "library":
            return {"ok": False, "error": "当前文件位置已变化，无法自动恢复。请手动检查文件。"}
        if matched_book.get("repo_area") != "archive":
            return {"ok": False, "error": "当前文件位置已变化，无法自动恢复。请手动检查文件。"}

        incoming_dir = root / "incoming"
        library_dir = root / "library"

        new_incoming_target = _unique_target(incoming_dir, new_library)
        old_library_target = _unique_target(library_dir, old_archive)

        shutil.move(str(new_library), str(new_incoming_target))
        try:
            shutil.move(str(old_archive), str(old_library_target))
        except Exception as e:
            try:
                shutil.move(str(new_incoming_target), str(new_library))
            except Exception:
                pass
            return {"ok": False, "error": f"恢复旧版失败: {e}"}

        now = now_ts()
        conn.execute(
            "UPDATE books SET repo_area = ?, current_path = ?, file_name = ?, status = ?, updated_at = ? WHERE id = ?",
            ("incoming", str(new_incoming_target), new_incoming_target.name, "normal", now, incoming_book_id),
        )
        conn.execute(
            "UPDATE books SET repo_area = ?, current_path = ?, file_name = ?, status = ?, updated_at = ? WHERE id = ?",
            ("library", str(old_library_target), old_library_target.name, "normal", now, matched_book_id),
        )
        conn.execute("UPDATE web_operation_records SET restored = 1 WHERE operation_id = ?", (operation_id,))

        restore_op_id = str(uuid.uuid4())[:12]
        restore_detail = {
            "original_operation_id": operation_id,
            "incoming_book_id": incoming_book_id,
            "matched_book_id": matched_book_id,
            "new_library_to_incoming": str(new_library_path),
            "old_archive_to_library": str(old_archive_path),
            "progress_restore_policy": "preserve_both",
        }
        conn.execute(
            """INSERT INTO web_operation_records (operation_id, operation_type, book_id, title, file_name, source_path, target_path, source_area, target_area, status, reversible, restored, created_at, detail_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'success', 0, 0, ?, ?)""",
            (restore_op_id, "restore_replace_library_version", incoming_book_id,
             incoming_book.get("title_norm") or incoming_book.get("title_raw") or incoming_book.get("file_name", ""),
             new_incoming_target.name, str(new_library), str(new_incoming_target), "library", "incoming",
             now, json.dumps(restore_detail, ensure_ascii=False)),
        )
        conn.commit()

        _write_log(root, f"restore_replace_library_version op_id={operation_id} new={new_library}→{new_incoming_target} old={old_archive}→{old_library_target} restore_op_id={restore_op_id}")

        return {
            "ok": True,
            "message": "已恢复替换操作",
            "new_incoming_path": str(new_incoming_target),
            "old_library_path": str(old_library_target),
            "restore_operation_id": restore_op_id,
        }
    finally:
        conn.close()
