from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .utils import ensure_dir, write_text_no_overwrite


REPO_DIRS = [
    "incoming",
    "library",
    "archive/replaced",
    "archive/duplicates",
    "archive/manual",
    "review_duplicates",
    "trash",
    "review_updates",
    "quarantine",
    "reports/duplicate",
    "reports/update",
    "reports/quality",
    "reports/group",
    "reports/errors",
    "db/backups",
    "cache/clean_text",
    "cache/fingerprints",
    "cache/chapter_index",
    "config",
    "logs",
    "exports",
]

DEFAULT_CONFIG = {
    "repo_version": 1,
    "scan": {"extensions": [".txt"], "changed_only_default": True},
    "safety": {"never_delete": True, "require_confirm_for_moves": True},
}

DEFAULT_CLEANING_RULES = {
    "ad_keywords": [
        "本书来自",
        "请收藏本站",
        "最新网址",
        "手机阅读",
        "无弹窗",
        "笔趣阁",
        "加入书签",
        "求推荐票",
        "求月票",
        "www.",
        "http://",
        "https://",
        "txt下载",
        "小说网",
        "最快更新",
        "最新章节",
        "请记住本站",
        "app下载",
        "微信公众号",
        "扫描二维码",
    ]
}

DEFAULT_SCORING_RULES = {
    "weights": {
        "integrity": 30,
        "cleanliness": 25,
        "chapters": 25,
        "metadata": 10,
        "trust": 10,
    }
}


def create_repo_dirs(repo: Path) -> None:
    for relative in REPO_DIRS:
        ensure_dir(repo / relative)


def create_default_configs(repo: Path) -> dict[str, bool]:
    created = {}
    files: list[tuple[str, dict[str, Any]]] = [
        ("config/config.yaml", DEFAULT_CONFIG),
        ("config/cleaning_rules.yaml", DEFAULT_CLEANING_RULES),
        ("config/scoring_rules.yaml", DEFAULT_SCORING_RULES),
    ]
    for relative, data in files:
        created[relative] = write_text_no_overwrite(
            repo / relative,
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        )
    return created


def load_yaml(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return default
    return data


def load_cleaning_rules(repo: Path) -> dict[str, Any]:
    return load_yaml(repo / "config" / "cleaning_rules.yaml", DEFAULT_CLEANING_RULES)
