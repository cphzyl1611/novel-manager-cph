from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ...db import connect as db_connect
from ...utils import ensure_dir, now_ts
from .operation_service import record_operation


def _get_book(conn, book_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    return dict(row) if row else None


def _validate_incoming_book(conn, book_id: int, root: Path) -> dict[str, Any]:
    """Validate that book is still in incoming area and file exists."""
    book = _get_book(conn, book_id)
    if book is None:
        return {"ok": False, "error_code": "book_not_found", "error": "小说不存在", "debug": {"book_id": book_id}}

    repo_area = book.get("repo_area", "")
    current_path = book.get("current_path", "")
    path_exists = False

    if current_path:
        try:
            path_exists = Path(current_path).exists()
        except Exception:
            pass

    if repo_area != "incoming":
        return {
            "ok": False,
            "error_code": "incoming_item_stale",
            "error": "该文件已不在新下载区，可能已经被处理。请刷新检测结果。",
            "debug": {"book_id": book_id, "current_repo_area": repo_area, "current_path": current_path, "path_exists": path_exists},
        }

    if not path_exists:
        return {
            "ok": False,
            "error_code": "incoming_file_missing",
            "error": "源文件不存在，可能已被移动或删除。请刷新检测结果。",
            "debug": {"book_id": book_id, "current_repo_area": repo_area, "current_path": current_path, "path_exists": path_exists},
        }

    return {"ok": True, "book": book}


def _safe_move(source: Path, dest_dir: Path) -> Path:
    ensure_dir(dest_dir)
    target = dest_dir / source.name
    if not target.exists():
        shutil.move(str(source), str(target))
        return target
    stem = target.stem
    tag = now_ts().replace(" ", "_").replace(":", "")
    for n in range(200):
        suffix = f"__{tag}" + (f"_{n}" if n else "")
        candidate = dest_dir / f"{stem}{suffix}{source.suffix}"
        if not candidate.exists():
            shutil.move(str(source), str(candidate))
            return candidate
    raise OSError("无法生成唯一目标文件名")


def _update_location(conn, book_id: int, area: str, new_path: Path) -> None:
    conn.execute(
        "UPDATE books SET repo_area = ?, current_path = ?, file_name = ?, updated_at = ? WHERE id = ?",
        (area, str(new_path), new_path.name, now_ts(), book_id),
    )
    conn.commit()


def _write_op(repo: Path, op_type: str, book_id: int, src: str, dst: str) -> None:
    log_dir = repo / "logs"
    ensure_dir(log_dir)
    with open(log_dir / "operations.log", "a", encoding="utf-8") as f:
        f.write(f"[{now_ts()}] {op_type} book_id={book_id} source={src} target={dst} success\n")


def import_to_library(repo_path: str, book_id: int) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    try:
        conn = db_connect(root)
    except Exception:
        return {"ok": False, "error": "无法连接数据库"}

    validation = _validate_incoming_book(conn, book_id, root)
    if not validation["ok"]:
        conn.close()
        return validation

    book = validation["book"]
    source = Path(book["current_path"])
    try:
        target = _safe_move(source, root / "library")
    except OSError as e:
        conn.close()
        return {"ok": False, "error": str(e)}
    _update_location(conn, book_id, "library", target)
    _write_op(root, "import_to_library", book_id, str(source), str(target))
    title = book.get("title_norm") or book.get("title_raw") or book.get("file_name", "")
    record_operation(repo_path, "import_to_library", book_id, title, target.name, str(source), str(target), "incoming", "library", reversible=True)
    conn.close()
    return {"ok": True, "action": "import_to_library", "book_id": book_id, "source_path": str(source), "target_path": str(target), "message": "已加入书架"}


def move_to_review_duplicates(repo_path: str, book_id: int) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    try:
        conn = db_connect(root)
    except Exception:
        return {"ok": False, "error": "无法连接数据库"}

    validation = _validate_incoming_book(conn, book_id, root)
    if not validation["ok"]:
        conn.close()
        return validation

    book = validation["book"]
    source = Path(book["current_path"])
    try:
        target = _safe_move(source, root / "review_duplicates")
    except OSError as e:
        conn.close()
        return {"ok": False, "error": str(e)}
    _update_location(conn, book_id, "review_duplicates", target)
    _write_op(root, "move_to_review_duplicates", book_id, str(source), str(target))
    title = book.get("title_norm") or book.get("title_raw") or book.get("file_name", "")
    record_operation(repo_path, "move_to_review_duplicates", book_id, title, target.name, str(source), str(target), "incoming", "review_duplicates", reversible=True)
    conn.close()
    return {"ok": True, "action": "move_to_review_duplicates", "book_id": book_id, "source_path": str(source), "target_path": str(target), "message": "已移入重复复核区"}


def compare_books(book_id: int, matched_book_id: int, repo_path: str) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    try:
        conn = db_connect(root)
    except Exception:
        return {"ok": False, "error": "无法连接数据库"}
    a = _get_book(conn, book_id)
    b = _get_book(conn, matched_book_id)
    conn.close()
    if a is None:
        return {"ok": False, "error": "新下载小说不存在"}
    if b is None:
        return {"ok": False, "error": "匹配小说不存在"}

    def _b(d, k): return d.get(k) or 0
    inc_ch, mat_ch = _b(a, "chapter_count"), _b(b, "chapter_count")
    inc_cc, mat_cc = _b(a, "char_count_clean"), _b(b, "char_count_clean")
    inc_q, mat_q = _b(a, "quality_score") or 0, _b(b, "quality_score") or 0

    return {
        "ok": True,
        "incoming": {"book_id": book_id, "title": a.get("title_norm") or a.get("title_raw") or a.get("file_name", ""), "file_name": a.get("file_name", ""), "repo_area": a.get("repo_area", ""), "chapter_count": inc_ch, "char_count_clean": inc_cc, "quality_score": inc_q, "current_path": a.get("current_path", "")},
        "matched": {"book_id": matched_book_id, "title": b.get("title_norm") or b.get("title_raw") or b.get("file_name", ""), "file_name": b.get("file_name", ""), "repo_area": b.get("repo_area", ""), "chapter_count": mat_ch, "char_count_clean": mat_cc, "quality_score": mat_q, "current_path": b.get("current_path", "")},
        "diff": {"chapter_delta": inc_ch - mat_ch, "char_count_delta": inc_cc - mat_cc, "quality_delta": round(inc_q - mat_q, 1), "incoming_longer": inc_cc > mat_cc},
        "recommendation": {"type": "manual_review", "message": "新版内容较多但建议人工确认后再替换。" if inc_cc > mat_cc else "新旧版本内容接近，建议人工对比后决定。"},
    }
