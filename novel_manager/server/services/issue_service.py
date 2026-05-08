from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def get_issues(repo_path: str) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    result = {
        "duplicate_count": 0,
        "update_count": 0,
        "rename_recommended": 0,
        "health_warnings": 0,
        "incoming_count": 0,
        "low_quality_count": 0,
        "suggestions": [],
    }
    if not root.exists():
        return result

    incoming_dir = root / "incoming"
    if incoming_dir.exists():
        result["incoming_count"] = len([p for p in incoming_dir.glob("*.txt") if p.is_file()])

    dup_data = _load_latest(root, "reports/duplicate", "duplicate_report_*.json")
    if dup_data:
        result["duplicate_count"] = len(dup_data.get("groups", []))

    update_data = _load_latest(root, "reports/update", "update_report_*.json")
    if update_data:
        result["update_count"] = sum(
            1 for c in update_data.get("candidates", [])
            if c.get("recommendation") == "replace_recommended"
        )

    rename_data = _load_latest(root, "reports/rename", "rename_plan_*.json")
    if rename_data:
        result["rename_recommended"] = sum(
            1 for s in rename_data.get("suggestions", [])
            if s.get("action") == "rename_recommended"
        )

    if result["rename_recommended"]:
        result["suggestions"].append({
            "type": "rename",
            "title": f"有 {result['rename_recommended']} 个文件名可以安全整理",
            "action": "go_rename",
        })
    if result["update_count"]:
        result["suggestions"].append({
            "type": "update",
            "title": f"有 {result['update_count']} 个推荐更新",
            "action": "go_updates",
        })
    if result["duplicate_count"]:
        result["suggestions"].append({
            "type": "duplicate",
            "title": f"有 {result['duplicate_count']} 组重复需要处理",
            "action": "go_duplicates",
        })

    return result


def _load_latest(root: Path, rel_dir: str, pattern: str) -> dict[str, Any] | None:
    directory = root / rel_dir
    if not directory.exists():
        return None
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
