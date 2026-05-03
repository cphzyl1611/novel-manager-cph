from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def file_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_text_no_overwrite(path: Path, text: str) -> bool:
    if path.exists():
        return False
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")
    return True


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rel_or_abs(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path.resolve())


def repo_path(repo: str | Path) -> Path:
    return Path(repo).expanduser().resolve()
