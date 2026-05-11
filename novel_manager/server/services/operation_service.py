from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from ...db import connect as db_connect
from ...utils import ensure_dir, now_ts

REVERSIBLE_TYPES = {"import_to_library", "move_to_review_duplicates", "replace_library_version"}
TYPE_LABELS = {"import_to_library": "加入书架", "move_to_review_duplicates": "移入重复复核区", "replace_library_version": "替换旧版", "restore_replace_library_version": "恢复替换"}
AREA_LABELS = {"incoming": "新下载区", "library": "小说库", "review_duplicates": "重复复核区", "archive": "归档区", "trash": "废弃区"}


def _ensure_table(repo: Path):
    conn = db_connect(repo)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS web_operation_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT UNIQUE,
            operation_type TEXT NOT NULL,
            book_id INTEGER,
            title TEXT,
            file_name TEXT,
            source_path TEXT,
            target_path TEXT,
            source_area TEXT,
            target_area TEXT,
            status TEXT DEFAULT 'success',
            reversible INTEGER DEFAULT 0,
            restored INTEGER DEFAULT 0,
            restore_operation_id TEXT,
            created_at TEXT,
            detail_json TEXT
        );
    """)
    conn.commit()
    return conn


def record_operation(repo_path: str, op_type: str, book_id: int, title: str, file_name: str, source_path: str, target_path: str, source_area: str, target_area: str, reversible: bool = False) -> str:
    root = Path(repo_path).expanduser().resolve()
    conn = _ensure_table(root)
    op_id = str(uuid.uuid4())[:12]
    conn.execute(
        """INSERT INTO web_operation_records (operation_id, operation_type, book_id, title, file_name, source_path, target_path, source_area, target_area, status, reversible, restored, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'success', ?, 0, ?)""",
        (op_id, op_type, book_id, title, file_name, source_path, target_path, source_area, target_area, 1 if reversible else 0, now_ts()),
    )
    conn.commit(); conn.close()
    _write_log(root, f"{op_type} book_id={book_id} source={source_path} target={target_path} op_id={op_id}")
    return op_id


def list_operations(repo_path: str, limit: int = 50, offset: int = 0, op_type: str = "", reversible: bool | None = None, restored: bool | None = None) -> dict:
    root = Path(repo_path).expanduser().resolve()
    try:
        conn = _ensure_table(root)
    except Exception:
        return {"items": [], "total": 0}
    clauses = ["1=1"]
    params: list = []
    if op_type:
        clauses.append("operation_type = ?"); params.append(op_type)
    if reversible is not None:
        clauses.append("reversible = ?"); params.append(1 if reversible else 0)
    if restored is not None:
        clauses.append("restored = ?"); params.append(1 if restored else 0)
    total = conn.execute(f"SELECT COUNT(*) FROM web_operation_records WHERE {' AND '.join(clauses)}", params).fetchone()[0]
    rows = conn.execute(f"SELECT * FROM web_operation_records WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
    conn.close()
    return {"items": [_row_item(dict(r)) for r in rows], "total": total}


def get_operation(repo_path: str, operation_id: str) -> dict | None:
    root = Path(repo_path).expanduser().resolve()
    try:
        conn = _ensure_table(root)
    except Exception:
        return None
    row = conn.execute("SELECT * FROM web_operation_records WHERE operation_id = ?", (operation_id,)).fetchone()
    conn.close()
    return _row_item(dict(row)) if row else None


def restore_operation(repo_path: str, operation_id: str) -> dict:
    root = Path(repo_path).expanduser().resolve()
    try:
        conn = _ensure_table(root)
    except Exception:
        return {"ok": False, "error": "无法连接数据库"}
    row = conn.execute("SELECT * FROM web_operation_records WHERE operation_id = ?", (operation_id,)).fetchone()
    if row is None:
        conn.close(); return {"ok": False, "error": "操作记录不存在"}
    rec = dict(row)
    conn.close()

    if not rec["reversible"]:
        return {"ok": False, "error": "该操作不可恢复"}
    if rec["restored"]:
        return {"ok": False, "error": "该操作已经恢复过，不能重复恢复"}
    if rec["operation_type"] not in REVERSIBLE_TYPES:
        return {"ok": False, "error": "该操作类型不支持恢复"}

    if rec["operation_type"] == "replace_library_version":
        from .version_replace_service import restore_replace_library_version
        return restore_replace_library_version(repo_path, operation_id)

    try:
        conn = _ensure_table(root)
    except Exception:
        return {"ok": False, "error": "无法连接数据库"}

    op_type = rec["operation_type"]
    book_id = rec["book_id"]
    target_path = rec["target_path"]

    target = Path(target_path)
    if not target.exists():
        conn.close(); return {"ok": False, "error": "当前文件位置已变化，无法自动恢复。请手动检查文件。"}
    book_row = conn.execute("SELECT repo_area FROM books WHERE id = ?", (book_id,)).fetchone()
    if book_row is None:
        conn.close(); return {"ok": False, "error": "相关书籍记录不存在"}
    if book_row[0] != rec["target_area"]:
        conn.close(); return {"ok": False, "error": "当前文件位置已变化，无法自动恢复。请手动检查文件。"}

    incoming = root / "incoming"
    ensure_dir(incoming)
    dest = incoming / target.name
    if dest.exists():
        tag = now_ts().replace(" ", "_").replace(":", "")
        dest = incoming / f"{target.stem}__restore_{tag}{target.suffix}"
        if dest.exists():
            conn.close(); return {"ok": False, "error": "目标文件已存在，无法自动恢复"}

    shutil.move(str(target), str(dest))
    conn.execute("UPDATE books SET repo_area = ?, current_path = ?, file_name = ?, updated_at = ? WHERE id = ?", ("incoming", str(dest), dest.name, now_ts(), book_id))
    conn.execute("UPDATE web_operation_records SET restored = 1 WHERE operation_id = ?", (operation_id,))
    restore_op_id = str(uuid.uuid4())[:12]
    conn.execute(
        """INSERT INTO web_operation_records (operation_id, operation_type, book_id, title, file_name, source_path, target_path, source_area, target_area, status, reversible, restored, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'success', 0, 0, ?)""",
        (restore_op_id, f"restore_{op_type}", book_id, rec["title"], rec["file_name"], str(target), str(dest), rec["target_area"], "incoming", now_ts()),
    )
    conn.commit(); conn.close()
    _write_log(root, f"restore_{op_type} book_id={book_id} source={target} target={dest} restore_op_id={restore_op_id}")
    return {"ok": True, "message": "已恢复到新下载区", "source_path": str(target), "target_path": str(dest), "restore_operation_id": restore_op_id}


def _row_item(d: dict) -> dict:
    return {
        "operation_id": d.get("operation_id"), "operation_type": d.get("operation_type"),
        "operation_label": TYPE_LABELS.get(d.get("operation_type"), d.get("operation_type")),
        "book_id": d.get("book_id"), "title": d.get("title"), "file_name": d.get("file_name"),
        "source_area": AREA_LABELS.get(d.get("source_area"), d.get("source_area") or ""),
        "target_area": AREA_LABELS.get(d.get("target_area"), d.get("target_area") or ""),
        "source_path": d.get("source_path"), "target_path": d.get("target_path"),
        "status": d.get("status"), "reversible": bool(d.get("reversible")),
        "restored": bool(d.get("restored")), "created_at": d.get("created_at"),
    }


def _write_log(repo: Path, summary: str) -> None:
    log_dir = repo / "logs"
    ensure_dir(log_dir)
    with open(log_dir / "operations.log", "a", encoding="utf-8") as f:
        f.write(f"[{now_ts()}] {summary}\n")
