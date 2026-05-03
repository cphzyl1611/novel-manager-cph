from __future__ import annotations

from typing import Any

AREA_LABELS = {
    "all": "全部区域",
    "library": "小说库",
    "incoming": "新下载区",
    "archive": "归档区",
    "review_duplicates": "重复复核区",
    "trash": "废弃区",
}

QUALITY_LABELS = {
    "excellent": "优秀",
    "good": "良好",
    "fair": "一般",
    "poor": "较差",
}

GROUP_TYPE_LABELS = {
    "duplicate": "精确重复",
    "exact_duplicate": "精确重复",
    "near_duplicate": "近似重复",
    "work_group": "同书版本",
    "same_work": "同书版本",
}

ACTION_LABELS = {
    "dry_run": "预览操作",
    "dry-run": "预览操作",
    "apply": "执行",
    "confirm": "确认执行",
    "rename_recommended": "建议改名",
    "manual_review": "需要人工确认",
    "no_change": "无需修改",
    "replace_recommended": "建议更新",
    "update_recommended": "建议更新",
    "reject": "不建议更新",
    "review": "需要复核",
    "archive_candidate": "建议移入复核区",
    "keep": "建议保留",
    "primary": "推荐保留",
    "secondary": "候选版本",
    "duplicate": "重复候选",
}

REPORT_LABELS = {
    "duplicate": "重复检测",
    "quality": "质量检查",
    "update": "更新检测",
    "rename": "文件名整理",
    "health": "健康检查",
    "summary": "汇总报告",
    "diagnostic": "诊断报告",
    "errors": "扫描错误",
    "group": "同书版本",
}

RISK_LABELS = {
    "author_missing": "作者缺失",
    "author_suspicious": "作者疑似误识别",
    "target_name_conflict": "文件名冲突",
    "manual_review_needed": "需要人工确认",
    "source_prefix_removed": "已清理来源前缀",
    "status_extracted": "已提取状态",
    "dirty_file_name": "文件名仍含噪声",
    "dirty_title_norm": "标题仍含噪声",
    "missing_file": "文件不存在",
    "target_same_as_current": "目标名与当前相同",
    "bracket_residue_removed": "已清理括号残留",
    "chapter_range_removed": "已清理章节范围",
    "title_cleaned_aggressively": "书名清理较强",
    "low_quality_book": "低质量小说",
    "mojibake_risk": "疑似乱码",
    "target_truncated": "目标名被截断",
    "possible_update_version": "可能是新版",
    "author_conflict": "作者冲突",
    "duplicate_book_group": "同书组风险",
    "conflict": "冲突",
}

SEVERITY_LABELS = {
    "error": "错误",
    "warning": "警告",
    "info": "提示",
}

OPERATION_LABELS = {
    "apply_rename": "执行重命名",
    "apply_update_archive_old": "归档旧版本",
    "apply_update_promote_new": "启用新版本",
    "move_to_trash": "移入废弃区",
    "refresh_metadata": "刷新元数据",
    "group_books_apply": "整理同书版本",
    "set_primary": "设置主版本",
    "merge_groups": "合并同书组",
    "split_group": "拆分同书组",
    "tag_book": "添加标签",
    "set_status": "设置阅读状态",
}

COMMAND_LABELS = {
    "scan": "扫描小说",
    "find-duplicates": "检测重复与版本",
    "check-updates": "检查更新候选",
    "rename-plan": "生成重命名计划",
    "apply-renames": "预览改名操作",
    "apply-updates": "预览更新操作",
    "stage-duplicates": "预览移入重复复核区",
    "post-rename-check": "健康检查",
    "refresh-metadata": "预览刷新元数据",
    "auto-tag": "预览自动标签",
    "quality-report": "质量检查",
    "summary-report": "生成汇总报告",
    "report-index": "生成报告索引",
}


def label(mapping: dict[str, str], value: object) -> str:
    if value is None:
        return ""
    return mapping.get(str(value), str(value))


def area_label(value: object) -> str:
    return label(AREA_LABELS, value)


def quality_label(value: object) -> str:
    return label(QUALITY_LABELS, value)


def group_type_label(value: object) -> str:
    return label(GROUP_TYPE_LABELS, value)


def action_label(value: object) -> str:
    return label(ACTION_LABELS, value)


def report_label(value: object) -> str:
    return label(REPORT_LABELS, value)


def risk_label(value: object) -> str:
    return label(RISK_LABELS, value)


def severity_label(value: object) -> str:
    return label(SEVERITY_LABELS, value)


def operation_label(value: object) -> str:
    return label(OPERATION_LABELS, value)


def command_label(value: object) -> str:
    return label(COMMAND_LABELS, value)


def risks_label(values: object) -> str:
    if not values:
        return ""
    if isinstance(values, str):
        raw = [item.strip() for item in values.split(",") if item.strip()]
    else:
        raw = [str(item) for item in values]
    return "，".join(risk_label(item) for item in raw)


def value_from_label(mapping: dict[str, str], text: str) -> str:
    for key, value in mapping.items():
        if value == text:
            return key
    return text


def yes_no(value: Any) -> str:
    return "是" if bool(value) else "否"
