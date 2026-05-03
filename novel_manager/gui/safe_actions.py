from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


RENAME_BLOCKING_RISKS = {"target_name_conflict", "manual_review_needed", "author_suspicious", "target_truncated"}
UPDATE_BLOCKING_RISKS = {"author_conflict", "low_coverage", "possible_truncated_new_version"}


def is_safe_rename_item(item: dict[str, Any]) -> bool:
    risks = set(item.get("risk_flags") or [])
    current = Path(str(item.get("current_path") or ""))
    target = Path(str(item.get("target_path_preview") or item.get("target_path") or ""))
    if item.get("action") != "rename_recommended":
        return False
    if risks & RENAME_BLOCKING_RISKS:
        return False
    if not current.exists():
        return False
    if not target or target.exists():
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
