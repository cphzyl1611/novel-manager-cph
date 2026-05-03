from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .db import db_path
from .tag_manager import tag_status_summary


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _display_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_summary_dir(repo: Path) -> Path:
    path = repo / "reports" / "summary"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _latest_apply_updates_log(repo: Path) -> Path | None:
    log_dir = repo / "logs"
    if not log_dir.exists():
        return None
    files = [path for path in log_dir.glob("apply_updates_*.json") if path.is_file()]
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def _latest_apply_renames_log(repo: Path) -> Path | None:
    log_dir = repo / "logs"
    if not log_dir.exists():
        return None
    files = [path for path in log_dir.glob("apply_renames_*.json") if path.is_file()]
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def _latest_rename_plan(repo: Path) -> Path | None:
    report_dir = repo / "reports" / "rename"
    if not report_dir.exists():
        return None
    files = [path for path in report_dir.glob("rename_plan_*.json") if path.is_file()]
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def _latest_health_report(repo: Path) -> Path | None:
    report_dir = repo / "reports" / "health"
    if not report_dir.exists():
        return None
    files = [path for path in report_dir.glob("post_rename_check_*.json") if path.is_file()]
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def _tag_status_section(repo: Path) -> str:
    path = db_path(repo)
    if not path.exists():
        return ""
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        summary = tag_status_summary(conn)
        conn.close()
    except sqlite3.Error:
        return ""
    lines = [
        "## 标签与阅读状态汇总",
        "",
        f"- 标签总数：{summary['tag_total']}",
        f"- 已打标签书籍数：{summary['tagged_books']}",
        f"- 未打标签书籍数：{summary['untagged_books']}",
        f"- 未设置 reading_status 的书籍数量：{summary['unset_reading_status']}",
        f"- 自动标签数量：{summary['source_counts'].get('auto', 0)}",
        f"- 手动标签数量：{summary['source_counts'].get('manual', 0)}",
        "",
        "各 category 标签数量：",
        "",
    ]
    for category, count in sorted(summary["category_counts"].items()):
        lines.append(f"- {category}: {count}")
    lines.extend(["", "使用最多的前 20 个标签：", ""])
    for tag in summary["top_tags"]:
        lines.append(f"- {tag['name']} ({tag.get('category') or 'custom'}): {tag['book_count']}")
    lines.extend(["", "各 reading_status 数量：", ""])
    for status, count in sorted(summary["reading_status_counts"].items()):
        lines.append(f"- {status}: {count}")
    return "\n".join(lines).rstrip() + "\n"


def _rename_plan_section(repo: Path) -> str:
    path = _latest_rename_plan(repo)
    if not path:
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    return "\n".join(
        [
            "## 重命名建议汇总",
            "",
            f"- rename_recommended 数量：{stats.get('rename_recommended', 0)}",
            f"- no_change 数量：{stats.get('no_change', 0)}",
            f"- manual_review 数量：{stats.get('manual_review', 0)}",
            f"- conflict 数量：{stats.get('target_name_conflict', 0)}",
            f"- author_missing 数量：{stats.get('author_missing', 0)}",
            f"- target_truncated 数量：{stats.get('target_truncated', 0)}",
            f"- rename_plan 报告路径：{_code(path)}",
        ]
    ).rstrip() + "\n"


def _health_section(repo: Path) -> str:
    path = _latest_health_report(repo)
    if not path:
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    return "\n".join(
        [
            "## 健康检查汇总",
            "",
            f"- error 数量：{stats.get('error_count', 0)}",
            f"- warning 数量：{stats.get('warning_count', 0)}",
            f"- missing file 数量：{stats.get('missing_file_count', 0)}",
            f"- dirty file_name 数量：{stats.get('dirty_file_name_count', 0)}",
            f"- dirty title_norm 数量：{stats.get('dirty_title_norm_count', 0)}",
            f"- metadata mismatch 数量：{stats.get('metadata_mismatch_count', 0)}",
            f"- post_rename_check 报告路径：{_code(path)}",
        ]
    ).rstrip() + "\n"


def _latest_report(repo: Path, relative_dir: str, pattern: str) -> Path | None:
    report_dir = repo / relative_dir
    if not report_dir.exists():
        return None
    files = [path for path in report_dir.glob(pattern) if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def _resolve_report_path(repo: Path, value: str | Path | None, relative_dir: str, pattern: str) -> Path | None:
    if value:
        path = Path(value)
        if path.is_absolute() or path.exists():
            return path
        return repo / path
    return _latest_report(repo, relative_dir, pattern)


def _load_json(path: Path | None, expected_key: str) -> tuple[dict[str, Any] | None, str | None]:
    if path is None:
        return None, "未找到报告文件。"
    if not path.exists():
        return None, f"报告文件不存在：{path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"JSON 解析失败：{exc}"
    except OSError as exc:
        return None, f"读取报告失败：{exc}"
    if not isinstance(data, dict):
        return None, "JSON 顶层结构不是对象。"
    if expected_key not in data:
        return data, f"JSON 缺少预期字段：{expected_key}"
    if not isinstance(data.get(expected_key), list):
        return data, f"JSON 字段 {expected_key} 不是列表。"
    return data, None


def _code(value: Any) -> str:
    if value is None or value == "":
        return "`-`"
    return f"`{str(value).replace('`', '')}`"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _book_path(book: dict[str, Any]) -> str:
    return str(book.get("current_path") or book.get("path") or "")


def _book_name(book: dict[str, Any]) -> str:
    path = _book_path(book)
    return str(book.get("file_name") or (Path(path).name if path else "-"))


def _reasons(book: dict[str, Any]) -> str:
    reasons = book.get("quality_reasons")
    if isinstance(reasons, list):
        return "；".join(str(item) for item in reasons[:3]) or "-"
    raw = book.get("quality_reasons_json")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return "；".join(str(item) for item in parsed[:3]) or "-"
        except json.JSONDecodeError:
            return raw[:120] or "-"
    return "-"


def _duplicate_groups(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not data:
        return []
    groups = data.get("groups")
    return groups if isinstance(groups, list) else []


def _quality_books(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not data:
        return []
    books = data.get("books")
    return [book for book in books if isinstance(book, dict)] if isinstance(books, list) else []


def _scan_errors(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not data:
        return []
    errors = data.get("errors")
    return [error for error in errors if isinstance(error, dict)] if isinstance(errors, list) else []


def _group_candidates(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not data:
        return []
    candidates = data.get("candidates")
    return [item for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else []


def _diagnostic_pairs(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not data:
        return []
    pairs = data.get("pairs")
    return [item for item in pairs if isinstance(item, dict)] if isinstance(pairs, list) else []


def _update_candidates(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not data:
        return []
    candidates = data.get("candidates")
    return [item for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else []


def _member_book(member: dict[str, Any]) -> dict[str, Any]:
    book = member.get("book")
    return book if isinstance(book, dict) else {}


def _recommended_keep_path(group: dict[str, Any]) -> str:
    keep_id = group.get("recommended_keep_book_id")
    members = group.get("members") if isinstance(group.get("members"), list) else []
    for member in members:
        if member.get("suggested_role") == "keep":
            return _book_path(_member_book(member))
    for member in members:
        book = _member_book(member)
        if book.get("id") == keep_id:
            return _book_path(book)
    return "-"


def _quality_table(books: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| book_id | 文件名 | 路径 | 质量分 | 等级 | 章节 | 广告行 | 乱码率 | 主要扣分原因 |",
        "|---:|---|---|---:|---|---:|---:|---:|---|",
    ]
    for book in books:
        lines.append(
            "| {id} | {name} | {path} | {score:.2f} | {level} | {chapters} | {ads} | {mojibake:.4f} | {reasons} |".format(
                id=book.get("id", "-"),
                name=_code(_book_name(book)),
                path=_code(_book_path(book)),
                score=_num(book.get("quality_score")),
                level=book.get("quality_level") or "-",
                chapters=int(_num(book.get("chapter_count"))),
                ads=int(_num(book.get("ad_line_count"))),
                mojibake=_num(book.get("mojibake_rate")),
                reasons=_reasons(book),
            )
        )
    if not books:
        lines.append("| - | - | - | - | - | - | - | - | - |")
    return lines


def _build_markdown(
    repo: Path,
    duplicate_path: Path | None,
    quality_path: Path | None,
    error_path: Path | None,
    group_path: Path | None,
    diagnostic_path: Path | None,
    update_path: Path | None,
    duplicate_data: dict[str, Any] | None,
    quality_data: dict[str, Any] | None,
    error_data: dict[str, Any] | None,
    group_data: dict[str, Any] | None,
    diagnostic_data: dict[str, Any] | None,
    update_data: dict[str, Any] | None,
    load_errors: dict[str, str | None],
) -> str:
    groups = _duplicate_groups(duplicate_data)
    books = _quality_books(quality_data)
    errors = _scan_errors(error_data)
    group_candidates = _group_candidates(group_data)
    diagnostic_pairs = _diagnostic_pairs(diagnostic_data)
    update_candidates = _update_candidates(update_data)
    raw_count = sum(1 for group in groups if group.get("group_type") == "raw_exact")
    clean_count = sum(1 for group in groups if group.get("group_type") == "clean_exact")
    near_groups = [group for group in groups if group.get("group_type") == "near_duplicate"]
    near_high = sum(1 for group in near_groups if group.get("confidence_level") == "high_confidence")
    near_probable = sum(1 for group in near_groups if group.get("confidence_level") == "probable_duplicate")
    near_suspicious = sum(1 for group in near_groups if group.get("confidence_level") == "suspicious")
    near_updates = sum(1 for group in near_groups if "possible_update_version" in (group.get("risk_flags") or []))
    near_author_conflicts = sum(1 for group in near_groups if "author_conflict" in (group.get("risk_flags") or []))
    near_manual_review = sum(1 for group in near_groups if group.get("manual_review") or group.get("recommended_action") == "manual_review")
    move_count = sum(
        1
        for group in groups
        for member in (group.get("members") if isinstance(group.get("members"), list) else [])
        if member.get("suggested_role") in {"archive_candidate", "review"}
    )
    quality_problem_books = [
        book
        for book in books
        if _num(book.get("quality_score")) < 50
        or book.get("quality_level") == "poor"
        or int(_num(book.get("duplicate_chapter_count"))) > 0
        or int(_num(book.get("missing_chapter_count"))) > 0
        or int(_num(book.get("chapter_order_error_count"))) > 0
        or int(_num(book.get("truncated_risk"))) == 1
        or _num(book.get("mojibake_rate")) > 0.03
    ]
    manual_check_count = len(quality_problem_books) + len(errors) + move_count

    lines: list[str] = [
        "# 小说库整理汇总报告",
        "",
        "## 1. 基本信息",
        "",
        f"- 生成时间：{_display_time()}",
        f"- 仓库路径：{_code(repo)}",
        f"- 使用的 duplicate_report 文件：{_code(duplicate_path)}",
        f"- 使用的 quality_report 文件：{_code(quality_path)}",
        f"- 使用的 scan_error_report 文件：{_code(error_path)}",
        "",
    ]
    for name, error in load_errors.items():
        if error:
            lines.append(f"- {name} 状态：{error}")
    if any(load_errors.values()):
        lines.append("")

    if near_groups:
        lines.extend(
            [
                "## 近似重复统计",
                "",
                f"- near_duplicate 近似重复候选数量：{len(near_groups)}",
                f"- high_confidence 数量：{near_high}",
                f"- probable_duplicate 数量：{near_probable}",
                f"- suspicious 数量：{near_suspicious}",
                f"- possible_update_version 数量：{near_updates}",
                f"- author_conflict 数量：{near_author_conflicts}",
                f"- 需要人工复核数量：{near_manual_review}",
                "",
            ]
        )

    lines.extend(
        [
            "## 2. 总体概览",
            "",
            f"- 重复组数量：{len(groups)}",
            f"- raw_exact 重复组数量：{raw_count}",
            f"- clean_exact 重复组数量：{clean_count}",
            f"- 质量报告中的文件数量：{len(books)}",
            f"- 扫描错误数量：{len(errors)}",
            f"- 需要人工检查的文件数量：{manual_check_count}",
            f"- 推荐移动到 review_duplicates 的文件数量：{move_count}",
            "",
            "## 3. 重复检测汇总",
            "",
        ]
    )

    if not groups:
        lines.extend(["未发现可汇总的重复组。", ""])
    for index, group in enumerate(groups, 1):
        lines.extend(
            [
                f"### 重复组 {group.get('id', index)}：{group.get('group_type', '-')}",
                "",
                f"- 置信度：{group.get('confidence', '-')}",
                "",
                "推荐保留：",
                "",
                f"- {_code(_recommended_keep_path(group))}",
                "",
                "推荐理由：",
                "",
                f"> {group.get('reason_summary') or '报告未提供推荐理由。'}",
                "",
                "其他文件：",
                "",
                "| 角色 | 文件 | 质量分 | 建议 |",
                "|---|---|---:|---|",
            ]
        )
        members = group.get("members") if isinstance(group.get("members"), list) else []
        other_members = [member for member in members if member.get("suggested_role") != "keep"]
        for member in other_members:
            book = _member_book(member)
            lines.append(
                "| {role} | {file} | {score:.2f} | {reason} |".format(
                    role=member.get("suggested_role") or "-",
                    file=_code(_book_path(book)),
                    score=_num(book.get("quality_score")),
                    reason=member.get("reason") or "-",
                )
            )
        if not other_members:
            lines.append("| - | - | - | - |")
        lines.append("")

    lowest = sorted(books, key=lambda book: _num(book.get("quality_score")))[:20]
    most_ads = sorted(books, key=lambda book: _num(book.get("ad_line_count")), reverse=True)[:20]
    most_mojibake = sorted(books, key=lambda book: _num(book.get("mojibake_rate")), reverse=True)[:20]
    chapter_abnormal = [
        book
        for book in books
        if int(_num(book.get("duplicate_chapter_count"))) > 0
        or int(_num(book.get("missing_chapter_count"))) > 0
        or int(_num(book.get("chapter_order_error_count"))) > 0
        or int(_num(book.get("truncated_risk"))) == 1
    ][:20]

    lines.extend(["## 4. 质量问题汇总", "", "### 4.1 质量分最低的文件", ""])
    lines.extend(_quality_table(lowest))
    lines.extend(["", "### 4.2 广告行最多的文件", ""])
    lines.extend(_quality_table(most_ads))
    lines.extend(["", "### 4.3 乱码率最高的文件", ""])
    lines.extend(_quality_table(most_mojibake))
    lines.extend(["", "### 4.4 疑似章节异常文件", ""])
    lines.extend(_quality_table(chapter_abnormal))
    lines.extend(["", "## 5. 扫描错误汇总", ""])

    if not errors:
        lines.extend(["本次扫描没有发现读取错误。", ""])
    else:
        counter = Counter(str(error.get("error_type") or "unknown") for error in errors)
        lines.append(f"- 错误总数：{len(errors)}")
        lines.append("")
        lines.append("按 error_type 统计：")
        lines.append("")
        for error_type, count in counter.most_common():
            lines.append(f"- {error_type}: {count}")
        lines.extend(
            [
                "",
                "错误文件列表：",
                "",
                "| 文件 | 错误类型 | 错误信息 | 建议处理方式 |",
                "|---|---|---|---|",
            ]
        )
        for error in errors:
            lines.append(
                "| {path} | {type} | {message} | {advice} |".format(
                    path=_code(error.get("file_path")),
                    type=error.get("error_type") or "-",
                    message=str(error.get("error_message") or "-").replace("\n", " ")[:160],
                    advice="手动检查编码或文件完整性；必要时移动到 quarantine。",
                )
            )
        lines.append("")

    lines.extend(["## 6. 建议下一步操作", ""])
    if group_path or group_candidates:
        auto_apply_count = sum(1 for item in group_candidates if item.get("auto_apply"))
        manual_review_count = sum(1 for item in group_candidates if item.get("manual_review"))
        author_conflict_count = sum(1 for item in group_candidates if "作者冲突" in (item.get("risks") or []))
        primary_count = sum(1 for item in group_candidates if item.get("recommended_primary_book_id"))
        lines.extend(
            [
                "## 作品分组汇总",
                "",
                f"- 分组候选数量：{len(group_candidates)}",
                f"- 可自动 apply 数量：{auto_apply_count}",
                f"- manual_review 数量：{manual_review_count}",
                f"- 作者冲突数量：{author_conflict_count}",
                f"- 推荐主版本数量：{primary_count}",
                f"- group_report 路径：{_code(group_path)}",
                "",
            ]
        )

    if diagnostic_path or diagnostic_pairs:
        accepted = [p for p in diagnostic_pairs if str(p.get("filter_status") or "").startswith("accepted")]
        rejected = [p for p in diagnostic_pairs if str(p.get("filter_status") or "").startswith("rejected")]
        skipped_exact = sum(1 for p in diagnostic_pairs if p.get("filter_status") == "skipped_exact_duplicate")
        skipped_group = sum(1 for p in diagnostic_pairs if p.get("filter_status") == "skipped_same_work_group")
        avg_score = sum(float(p.get("same_work_score") or 0) for p in diagnostic_pairs) / len(diagnostic_pairs) if diagnostic_pairs else 0
        top_pairs = sorted(diagnostic_pairs, key=lambda p: float(p.get("same_work_score") or 0), reverse=True)[:10]
        lines.extend(
            [
                "## 近似重复诊断",
                "",
                f"- 候选对数量：{len(diagnostic_pairs)}",
                f"- accepted 数量：{len(accepted)}",
                f"- rejected 数量：{len(rejected)}",
                f"- skipped_exact_duplicate 数量：{skipped_exact}",
                f"- skipped_same_work_group 数量：{skipped_group}",
                f"- 平均 same_work_score：{avg_score:.4f}",
                f"- diagnostic_report 路径：{_code(diagnostic_path)}",
                "",
                "| A | B | same_work_score | filter_status |",
                "|---|---|---:|---|",
            ]
        )
        for pair in top_pairs:
            lines.append(f"| `{pair.get('file_a')}` | `{pair.get('file_b')}` | {float(pair.get('same_work_score') or 0):.4f} | {pair.get('filter_status')} |")
        lines.append("")

    if update_path or update_candidates:
        replace_count = sum(1 for c in update_candidates if c.get("recommendation") == "replace_recommended")
        manual_count = sum(1 for c in update_candidates if c.get("recommendation") == "manual_review")
        reject_count = sum(1 for c in update_candidates if c.get("recommendation") == "reject")
        author_conflict = sum(1 for c in update_candidates if "author_conflict" in (c.get("risk_flags") or []))
        quality_drop = sum(1 for c in update_candidates if "quality_drop" in (c.get("risk_flags") or []))
        ad_inc = sum(1 for c in update_candidates if "ad_line_increase" in (c.get("risk_flags") or []))
        mojibake_inc = sum(1 for c in update_candidates if "mojibake_increase" in (c.get("risk_flags") or []))
        lines.extend(
            [
                "## 更新检测汇总",
                "",
                f"- 更新候选数量：{len(update_candidates)}",
                f"- replace_recommended 数量：{replace_count}",
                f"- manual_review 数量：{manual_count}",
                f"- reject 数量：{reject_count}",
                f"- author_conflict 数量：{author_conflict}",
                f"- quality_drop 数量：{quality_drop}",
                f"- ad_line_increase 数量：{ad_inc}",
                f"- mojibake_increase 数量：{mojibake_inc}",
                f"- update_report 路径：{_code(update_path)}",
                "",
            ]
        )

    if groups:
        lines.extend(
            [
                "- 建议先打开 duplicate_report.html 人工确认。",
                "- 然后执行 `stage-duplicates --dry-run` 查看移动计划。",
                "- 确认无误后再执行 `--confirm`。",
            ]
        )
    if quality_problem_books:
        lines.extend(
            [
                "- 建议优先人工检查质量分最低的文件。",
                "- 对广告行多、乱码率高的文件暂不自动移动。",
            ]
        )
    if errors:
        lines.extend(
            [
                "- 建议手动检查编码或文件完整性。",
                "- 必要时移动到 quarantine。",
            ]
        )
    if not groups and not errors:
        lines.append("- 当前库状态较干净：未发现重复组，也没有扫描读取错误。")
    return "\n".join(lines).rstrip() + "\n"


def generate_summary_report(
    repo: Path,
    duplicate_report: str | Path | None = None,
    quality_report: str | Path | None = None,
    error_report: str | Path | None = None,
) -> Path:
    duplicate_path = _resolve_report_path(repo, duplicate_report, "reports/duplicate", "duplicate_report_*.json")
    quality_path = _resolve_report_path(repo, quality_report, "reports/quality", "quality_report_*.json")
    error_path = _resolve_report_path(repo, error_report, "reports/errors", "scan_error_report_*.json")
    group_path = _resolve_report_path(repo, None, "reports/group", "group_report_*.json")
    diagnostic_path = _resolve_report_path(repo, None, "reports/diagnostic", "near_diagnostic_*.json")
    update_path = _resolve_report_path(repo, None, "reports/update", "update_report_*.json")
    apply_log_path = _latest_apply_updates_log(repo)
    apply_renames_log_path = _latest_apply_renames_log(repo)

    duplicate_data, duplicate_error = _load_json(duplicate_path, "groups")
    quality_data, quality_error = _load_json(quality_path, "books")
    error_data, error_load_error = _load_json(error_path, "errors")
    group_data, group_error = _load_json(group_path, "candidates")
    diagnostic_data, diagnostic_error = _load_json(diagnostic_path, "pairs")
    update_data, update_error = _load_json(update_path, "candidates")
    markdown = _build_markdown(
        repo,
        duplicate_path,
        quality_path,
        error_path,
        group_path,
        diagnostic_path,
        update_path,
        duplicate_data,
        quality_data,
        error_data,
        group_data,
        diagnostic_data,
        update_data,
        {
            "duplicate_report": duplicate_error,
            "quality_report": quality_error,
            "scan_error_report": error_load_error,
            "group_report": group_error if group_path else None,
            "near_diagnostic": diagnostic_error if diagnostic_path else None,
            "update_report": update_error if update_path else None,
        },
    )
    if apply_log_path:
        try:
            apply_data = json.loads(apply_log_path.read_text(encoding="utf-8"))
            section = (
                "\n## 更新应用汇总\n\n"
                f"- dry_run：{apply_data.get('dry_run')}\n"
                f"- confirm：{apply_data.get('confirm')}\n"
                f"- planned_count：{apply_data.get('planned_count')}\n"
                f"- applied_count：{apply_data.get('applied_count')}\n"
                f"- skipped_count：{apply_data.get('skipped_count')}\n"
                f"- failed_count：{apply_data.get('failed_count')}\n"
                f"- apply log 路径：{_code(apply_log_path)}\n"
            )
            markdown = markdown.rstrip() + section + "\n"
        except (OSError, json.JSONDecodeError):
            pass
    if apply_renames_log_path:
        try:
            apply_data = json.loads(apply_renames_log_path.read_text(encoding="utf-8"))
            section = (
                "\n## 重命名应用汇总\n\n"
                f"- dry_run：{apply_data.get('dry_run')}\n"
                f"- confirm：{apply_data.get('confirm')}\n"
                f"- planned_count：{apply_data.get('planned_count')}\n"
                f"- renamed_count：{apply_data.get('renamed_count')}\n"
                f"- skipped_count：{apply_data.get('skipped_count')}\n"
                f"- failed_count：{apply_data.get('failed_count')}\n"
                f"- apply log 路径：{_code(apply_renames_log_path)}\n"
            )
            markdown = markdown.rstrip() + section + "\n"
        except (OSError, json.JSONDecodeError):
            pass
    tag_section = _tag_status_section(repo)
    if tag_section:
        markdown = markdown.rstrip() + "\n\n" + tag_section + "\n"
    rename_section = _rename_plan_section(repo)
    if rename_section:
        markdown = markdown.rstrip() + "\n\n" + rename_section + "\n"
    health_section = _health_section(repo)
    if health_section:
        markdown = markdown.rstrip() + "\n\n" + health_section + "\n"
    output = _ensure_summary_dir(repo) / f"summary_report_{_timestamp()}.md"
    output.write_text(markdown, encoding="utf-8")
    return output
