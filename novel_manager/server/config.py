from __future__ import annotations

from pathlib import Path

APP_NAME = "NovelHub"
APP_VERSION = "0.1.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_CONTENT_BYTES = 5 * 1024 * 1024


def is_safe_path(repo_path: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(repo_path.resolve())
        return True
    except ValueError:
        return False
