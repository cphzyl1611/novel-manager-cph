from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from .i18n import action_label, group_type_label, operation_label, risk_label, severity_label
from .safe_actions import is_safe_rename_item, is_safe_update_item

REPORT_DIRS = {
    "duplicate": "reports/duplicate",
    "rename": "reports/rename",
    "update": "reports/update",
    "health": "reports/health",
}

PATTERNS = {
    "duplicate": "duplicate_report_*.json",
    "rename": "rename_plan_*.json",
    "update": "update_report_*.json",
    "health": "post_rename_check_*.json",
}


def find_latest_report(repo: str | Path, report_type: str, suffix: str = "json") -> Path | None:
    directory = Path(repo) / REPORT_DIRS.get(report_type, "")
    if not directory.exists():
        return None
    pattern = PATTERNS.get(report_type, f"*.{suffix}")
    if suffix != "json":
        pattern = pattern.replace(".json", f".{suffix}")
    files = [p for p in directory.glob(pattern) if p.is_file()]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _load(path: str | Path | None, list_key: str) -> dict[str, Any]:
    if path is None:
        return {"ok": False, "error": "未找到报告文件", list_key: [], "summary_text": "还没有可用报告。"}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc), list_key: [], "summary_text": f"报告读取失败：{exc}"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "JSON 顶层不是对象", list_key: [], "summary_text": "报告格式不正确。"}
    value = data.get(list_key)
    if not isinstance(value, list):
        data[list_key] = []
    data["ok"] = True
    data["path"] = str(path)
    data["summary_text"] = summary_text(data)
    return data


def load_duplicate_report(path: str | Path | None) -> dict[str, Any]:
    return _load(path, "groups")


def load_rename_plan(path: str | Path | None) -> dict[str, Any]:
    return _load(path, "suggestions")


def load_update_report(path: str | Path | None) -> dict[str, Any]:
    return _load(path, "candidates")


def load_health_report(path: str | Path | None) -> dict[str, Any]:
    return _load(path, "issues")


def summarize_report(data: dict[str, Any]) -> dict[str, Any]:
    if "groups" in data:
        groups = data.get("groups") if isinstance(data.get("groups"), list) else []
        by_type = Counter(g.get("group_type") for g in groups)
        return {
            "count": len(groups),
            "exact_duplicate": by_type.get("exact_duplicate", 0) + by_type.get("duplicate", 0),
            "near_duplicate": by_type.get("near_duplicate", 0),
            "same_work": by_type.get("work_group", 0) + by_type.get("same_work", 0),
            "manual_review": sum(1 for g in groups if g.get("recommended_action") == "manual_review"),
        }
    if "suggestions" in data:
        rows = data.get("suggestions") if isinstance(data.get("suggestions"), list) else []
        return {
            "count": len(rows),
            "rename_recommended": sum(1 for r in rows if r.get("action") == "rename_recommended"),
            "manual_review": sum(1 for r in rows if r.get("action") == "manual_review"),
            "no_change": sum(1 for r in rows if r.get("action") == "no_change"),
            "conflict": sum(1 for r in rows if "target_name_conflict" in (r.get("risk_flags") or [])),
        }
    if "candidates" in data:
        rows = data.get("candidates") if isinstance(data.get("candidates"), list) else []
        recs = Counter(r.get("recommendation") for r in rows)
        return {
            "count": len(rows),
            "replace_recommended": recs.get("replace_recommended", 0) + recs.get("update_recommended", 0),
            "manual_review": recs.get("review", 0) + recs.get("manual_review", 0),
            "reject": recs.get("reject", 0),
        }
    if "issues" in data:
        rows = data.get("issues") if isinstance(data.get("issues"), list) else []
        by_code = Counter(r.get("code") for r in rows)
        return {
            "count": len(rows),
            "errors": sum(1 for r in rows if r.get("severity") == "error"),
            "warnings": sum(1 for r in rows if r.get("severity") == "warning"),
            "dirty_file_name": by_code.get("dirty_file_name", 0),
            "dirty_title_norm": by_code.get("dirty_title_norm", 0),
        }
    return {"count": 0}


def summary_text(data: dict[str, Any]) -> str:
    stats = summarize_report(data)
    if "groups" in data:
        return (
            f"发现 {stats['count']} 个重复/版本组；"
            f"精确重复 {stats['exact_duplicate']} 个，近似重复 {stats['near_duplicate']} 个，"
            f"同书版本 {stats['same_work']} 个。"
        )
    if "suggestions" in data:
        return (
            f"发现 {stats['count']} 条文件名建议；建议改名 {stats['rename_recommended']} 条，"
            f"需要人工确认 {stats['manual_review']} 条，冲突 {stats['conflict']} 条。"
        )
    if "candidates" in data:
        return (
            f"发现 {stats['count']} 个更新候选；建议更新 {stats['replace_recommended']} 个，"
            f"需要复核 {stats['manual_review']} 个，不建议更新 {stats['reject']} 个。"
        )
    if "issues" in data:
        return f"发现 {stats['count']} 个健康问题；错误 {stats['errors']} 个，警告 {stats['warnings']} 个。"
    return "暂无摘要。"


def _db_path(repo: str | Path) -> Path:
    return Path(repo) / "db" / "novel_repo.sqlite"


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    try:
        return int(conn.execute(sql, params).fetchone()[0] or 0)
    except sqlite3.Error:
        return 0


def collect_issue_summary(repo: str | Path | None) -> dict[str, Any]:
    empty = {
        "has_data": False,
        "duplicate": {"exact": 0, "near": 0, "same_work": 0},
        "update": {"incoming": 0, "recommended": 0, "review": 0, "reject": 0, "safe": 0},
        "rename": {"recommended": 0, "manual_review": 0, "conflict": 0, "no_change": 0, "safe": 0},
        "health": {"errors": 0, "warnings": 0, "dirty_file_name": 0, "dirty_title_norm": 0},
        "quality": {"mojibake": 0, "missing_chapter": 0, "many_ads": 0, "low_quality": 0},
    }
    if not repo:
        return empty
    root = Path(repo)
    dup = summarize_report(load_duplicate_report(find_latest_report(root, "duplicate")))
    rename_data = load_rename_plan(find_latest_report(root, "rename"))
    update_data = load_update_report(find_latest_report(root, "update"))
    ren = summarize_report(rename_data)
    upd = summarize_report(update_data)
    hea = summarize_report(load_health_report(find_latest_report(root, "health")))
    result = {
        "has_data": any(s.get("count", 0) for s in [dup, ren, upd, hea]),
        "duplicate": {
            "exact": dup.get("exact_duplicate", 0),
            "near": dup.get("near_duplicate", 0),
            "same_work": dup.get("same_work", 0),
        },
        "update": {
            "incoming": 0,
            "recommended": upd.get("replace_recommended", 0),
            "review": upd.get("manual_review", 0),
            "reject": upd.get("reject", 0),
            "safe": sum(1 for row in update_data.get("candidates", []) if is_safe_update_item(row)),
        },
        "rename": {
            "recommended": ren.get("rename_recommended", 0),
            "manual_review": ren.get("manual_review", 0),
            "conflict": ren.get("conflict", 0),
            "no_change": ren.get("no_change", 0),
            "safe": sum(1 for row in rename_data.get("suggestions", []) if is_safe_rename_item(row)),
        },
        "health": {
            "errors": hea.get("errors", 0),
            "warnings": hea.get("warnings", 0),
            "dirty_file_name": hea.get("dirty_file_name", 0),
            "dirty_title_norm": hea.get("dirty_title_norm", 0),
        },
        "quality": empty["quality"].copy(),
    }
    db = _db_path(root)
    if db.exists():
        conn = sqlite3.connect(db)
        try:
            result["update"]["incoming"] = _scalar(conn, "SELECT COUNT(*) FROM books WHERE repo_area = 'incoming'")
            result["quality"]["mojibake"] = _scalar(conn, "SELECT COUNT(*) FROM books WHERE COALESCE(mojibake_rate, 0) > 0")
            result["quality"]["missing_chapter"] = _scalar(conn, "SELECT COUNT(*) FROM books WHERE COALESCE(missing_chapter_count, 0) > 0")
            result["quality"]["many_ads"] = _scalar(conn, "SELECT COUNT(*) FROM books WHERE COALESCE(ad_line_count, 0) > 0")
            result["quality"]["low_quality"] = _scalar(conn, "SELECT COUNT(*) FROM books WHERE quality_level = 'poor' OR COALESCE(quality_score, 100) < 60")
        finally:
            conn.close()
    result["has_data"] = result["has_data"] or any(
        value for section in result.values() if isinstance(section, dict) for value in section.values()
    )
    return result


def summarize_operation_record(record: dict[str, Any]) -> str:
    op = operation_label(record.get("operation_type"))
    status = action_label(record.get("status")) if record.get("status") not in {"success", "failed", "skipped"} else {"success": "成功", "failed": "失败", "skipped": "跳过"}.get(record.get("status"), "")
    source = Path(str(record.get("source_path") or "")).name
    target = Path(str(record.get("target_path") or "")).name
    affected = target or source
    if not affected and record.get("book_id"):
        affected = f"对象 {record.get('book_id')}"
    if not affected:
        affected = "未记录对象"
    return f"{op}：{status or '已记录'}，{affected}"


def parse_operation_line(line: str) -> dict[str, Any]:
    try:
        data = json.loads(line)
        if isinstance(data, dict):
            data["summary"] = summarize_operation_record(data)
            return data
    except json.JSONDecodeError:
        pass
    return {"operation_type": "unknown", "summary": "历史日志记录", "raw": line}


def health_advice(issue: dict[str, Any]) -> str:
    code = str(issue.get("code") or "")
    area = str(issue.get("repo_area") or "")
    if code == "dirty_file_name" and area == "incoming":
        return "这是新下载区文件名噪声，不影响小说库。可以等待入库后再整理，或在文件名整理页处理新下载区。"
    if code == "dirty_title_norm":
        return "建议运行：预览刷新元数据。确认摘要无误后，再决定是否到命令行执行写入。"
    if code == "missing_file":
        return "数据库记录指向的文件不存在，请检查是否手动移动或删除。"
    if issue.get("severity") == "warning":
        return f"{severity_label('warning')}：请查看文件名整理或元数据预览。"
    return f"{risk_label(code) or '该问题需要人工确认'}。本页面不会修改小说文件。"
