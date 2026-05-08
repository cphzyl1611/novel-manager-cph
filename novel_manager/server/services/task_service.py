from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def get_updates_summary(repo_path: str) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    directory = root / "reports" / "update"
    result = {"replace_recommended": 0, "manual_review": 0, "reject": 0, "candidates": []}

    if not directory.exists():
        return result

    reports = sorted(directory.glob("update_report_*.json"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        return result

    try:
        data = json.loads(reports[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return result

    candidates = data.get("candidates", [])
    result["replace_recommended"] = sum(
        1 for c in candidates if c.get("recommendation") == "replace_recommended")
    result["manual_review"] = sum(
        1 for c in candidates if c.get("recommendation") == "review")
    result["reject"] = sum(
        1 for c in candidates if c.get("recommendation") == "reject")

    for c in candidates[:20]:
        result["candidates"].append({
            "old_file": c.get("old_file") or "",
            "new_file": c.get("new_file") or "",
            "recommendation": c.get("recommendation") or "",
            "risk_flags": c.get("risk_flags") or [],
            "reason_summary": c.get("reason_summary") or "",
        })

    return result
