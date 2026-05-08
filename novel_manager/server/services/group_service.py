from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ...utils import ensure_dir, now_ts


def list_groups(repo_path: str) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    library = root / "library"
    if not library.exists():
        return {"items": []}

    items = []
    root_books = [p for p in library.glob("*.txt") if p.is_file()]
    if root_books:
        items.append({"name": "默认分组", "path": str(library), "book_count": len(root_books)})

    for child in sorted(library.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            txt_count = len([p for p in child.glob("*.txt") if p.is_file()])
            items.append({"name": child.name, "path": str(child), "book_count": txt_count})
    return {"items": items}


def create_group(repo_path: str, name: str) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    library = root / "library"
    if not library.exists():
        ensure_dir(library)

    safe_name = _sanitize_name(name)
    if not safe_name:
        return {"ok": False, "error": "分组名称无效"}

    target = (library / safe_name).resolve()
    try:
        target.relative_to(library.resolve())
    except ValueError:
        return {"ok": False, "error": "分组路径必须在 library 目录下"}

    if target.exists():
        return {"ok": True, "name": safe_name, "path": str(target), "existed": True}

    ensure_dir(target)
    _write_log(root, f"create_group: {safe_name}")
    book_count = len([p for p in target.glob("*.txt") if p.is_file()])
    return {"ok": True, "name": safe_name, "path": str(target), "book_count": book_count, "existed": False}


def _sanitize_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|.]', "", name).strip()[:100]


def _write_log(repo: Path, summary: str) -> None:
    log_dir = repo / "logs"
    ensure_dir(log_dir)
    ts = now_ts()
    with open(log_dir / "server_operations.log", "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {summary}\n")
