from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .i18n import action_label, risk_label

RENAME_BLOCKING_RISKS = {"target_name_conflict", "manual_review_needed", "author_suspicious", "target_truncated"}
UPDATE_BLOCKING_RISKS = {"author_conflict", "low_coverage", "possible_truncated_new_version"}


def is_safe_rename_item(item: dict[str, Any]) -> bool:
    risks = set(item.get("risk_flags") or [])
    current_raw = str(item.get("current_path") or "").strip()
    target_raw = str(item.get("target_path_preview") or item.get("target_path") or "").strip()
    if item.get("action") != "rename_recommended":
        return False
    if risks & RENAME_BLOCKING_RISKS:
        return False
    if not current_raw:
        return False
    current = Path(current_raw)
    if not current.exists():
        return False
    if not target_raw:
        return False
    target = Path(target_raw)
    if target.exists():
        return False
    return True


def is_safe_update_item(item: dict[str, Any]) -> bool:
    risks = set(item.get("risk_flags") or [])
    if item.get("recommendation") not in {"replace_recommended", "update_recommended"}:
        return False
    if risks & UPDATE_BLOCKING_RISKS:
        return False
    if float(item.get("quality_delta") or 0) < -10:
        return False
    same_work = item.get("same_work_score")
    coverage = item.get("coverage_score")
    if same_work is not None and float(same_work) < 0.85:
        return False
    if coverage is not None and float(coverage) < 0.8:
        return False
    return True


def safe_rename_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    safe = sum(1 for row in rows if is_safe_rename_item(row))
    return {"safe": safe, "skipped": max(0, len(rows) - safe)}


def safe_update_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    safe = sum(1 for row in rows if is_safe_update_item(row))
    return {"safe": safe, "skipped": max(0, len(rows) - safe)}


def write_filtered_rename_plan(repo: str | Path, source_report: str | Path, selected: list[dict[str, Any]]) -> Path:
    safe_items = [item for item in selected if is_safe_rename_item(item)]
    return _write_filtered_report(repo, source_report, "reports/rename", "selected_rename_plan", "suggestions", safe_items)


def write_filtered_update_report(repo: str | Path, source_report: str | Path, selected: list[dict[str, Any]]) -> Path:
    safe_items = [item for item in selected if is_safe_update_item(item)]
    return _write_filtered_report(repo, source_report, "reports/update", "selected_update_report", "candidates", safe_items)


def rename_unsafe_reason(item: dict[str, Any]) -> str:
    reasons: list[str] = []
    risks = set(item.get("risk_flags") or [])
    if item.get("action") != "rename_recommended":
        reasons.append(f'处理建议为"{action_label(item.get("action"))}"，非建议改名')
    blocking = risks & RENAME_BLOCKING_RISKS
    if blocking:
        reasons.append("；".join(risk_label(r) for r in sorted(blocking)))
    current_raw = str(item.get("current_path") or "").strip()
    current = Path(current_raw) if current_raw else Path()
    if not current_raw:
        reasons.append("当前文件路径为空")
    elif not current.exists():
        reasons.append("当前文件不存在")
    target_raw = str(item.get("target_path_preview") or item.get("target_path") or "").strip()
    target = Path(target_raw) if target_raw else Path()
    if not target_raw:
        reasons.append("建议文件名为空")
    elif target.exists():
        reasons.append("目标文件已存在同名文件")
    if item.get("current_file_name") == item.get("target_file_name"):
        reasons.append("当前文件名与建议文件名相同")
    return "；".join(reasons) or "需要人工确认"


def should_check_rename_item_by_default(item: dict[str, Any]) -> bool:
    return is_safe_rename_item(item)


def can_user_toggle_rename_item(item: dict[str, Any]) -> bool:
    return is_safe_rename_item(item)


def get_rename_row_status(item: dict[str, Any]) -> dict[str, Any]:
    """Return structured first-column display info for a rename-plan row.

    Returns a dict with keys:
      checkable: bool        -- whether the user can toggle a checkbox
      checked_by_default: bool
      status_text: str       -- text shown in the cell (empty for checkable rows)
      reason: str            -- tooltip / explanation for the status
      category: str          -- "safe" | "manual" | "conflict" | "no_change" | "unsafe"
    """
    if is_safe_rename_item(item):
        return {
            "checkable": True,
            "checked_by_default": True,
            "status_text": "",
            "reason": "可安全处理，点击勾选或取消",
            "category": "safe",
        }

    risks = set(item.get("risk_flags") or [])
    action = item.get("action", "")

    if action == "manual_review":
        category, status = "manual", "需确认"
    elif action == "conflict" or "target_name_conflict" in risks:
        category, status = "conflict", "有冲突"
    elif action == "no_change":
        category, status = "no_change", "无需修改"
    else:
        category, status = "unsafe", "不可处理"

    return {
        "checkable": False,
        "checked_by_default": False,
        "status_text": status,
        "reason": rename_unsafe_reason(item),
        "category": category,
    }


def row_key(item: dict[str, Any]) -> str:
    """Generate a stable key for a rename-plan row to track checkbox state across filter changes."""
    book_id = item.get("book_id")
    if book_id is not None:
        return f"book:{book_id}"
    path = item.get("current_path")
    if path:
        return f"path:{path}"
    return f"name:{item.get('current_file_name', '')}:{item.get('target_file_name', '')}"


def is_row_checked(item: dict[str, Any], checked_keys: set[str]) -> bool:
    return row_key(item) in checked_keys


def update_checked_keys(
    checked_keys: set[str],
    item: dict[str, Any],
    checked: bool,
) -> set[str]:
    """Return a new set with the item's key added or removed."""
    key = row_key(item)
    new_keys = set(checked_keys)
    if checked:
        new_keys.add(key)
    else:
        new_keys.discard(key)
    return new_keys


def can_apply_visible_rows(visible_rows: list[dict[str, Any]], checked_keys: set[str]) -> bool:
    """Button should be enabled only when at least one checked item is a safe rename item."""
    for row in visible_rows:
        if is_row_checked(row, checked_keys) and is_safe_rename_item(row):
            return True
    return False


def initial_checked_keys(rows: list[dict[str, Any]]) -> set[str]:
    """Build the initial checked_keys set: safe items checked by default."""
    return {row_key(item) for item in rows if should_check_rename_item_by_default(item)}


def compute_rename_stats(
    visible_rows: list[dict[str, Any]], checked_keys: set[str]
) -> dict[str, int]:
    """Return category counts for visible rows."""
    total = len(visible_rows)
    safe = 0
    checked = 0
    manual = 0
    conflict = 0
    no_change = 0
    unsafe = 0

    for row in visible_rows:
        status = get_rename_row_status(row)
        cat = status["category"]
        if cat == "safe":
            safe += 1
            if is_row_checked(row, checked_keys):
                checked += 1
        elif cat == "manual":
            manual += 1
        elif cat == "conflict":
            conflict += 1
        elif cat == "no_change":
            no_change += 1
        else:
            unsafe += 1

    return {
        "total": total,
        "safe": safe,
        "checked": checked,
        "unselected_safe": safe - checked,
        "manual": manual,
        "conflict": conflict,
        "no_change": no_change,
        "unsafe": unsafe,
    }


def _write_filtered_report(repo: str | Path, source_report: str | Path, relative_dir: str, prefix: str, list_key: str, rows: list[dict[str, Any]]) -> Path:
    source = Path(source_report)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload[list_key] = rows
    payload["filtered_by_gui"] = True
    payload["source_report"] = str(source)
    payload["selected_count"] = len(rows)
    out_dir = Path(repo) / relative_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
