from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class QualityResult:
    quality_score: float
    quality_level: str
    quality_reasons: list[str]
    truncated_risk: int


def _level(score: float) -> str:
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "normal"
    return "poor"


def score_quality(
    *,
    char_count_clean: int,
    chapter_count: int,
    mojibake_rate: float,
    ad_line_count: int,
    ad_line_rate: float,
    duplicate_chapter_count: int,
    missing_chapter_count: int,
    chapter_order_error_count: int,
    file_name: str,
    title_norm: str,
    author_norm: str,
) -> QualityResult:
    reasons: list[str] = []

    integrity = 30.0
    truncated_risk = 0
    if char_count_clean < 1000:
        integrity -= 18
        truncated_risk = 1
        reasons.append("字数较少，存在疑似截断风险")
    elif char_count_clean < 10000:
        integrity -= 8
        reasons.append("字数偏少，建议人工检查完整性")
    else:
        reasons.append("文本长度较充足")

    cleanliness = 25.0
    if mojibake_rate > 0.03:
        cleanliness -= 15
        reasons.append("乱码率较高，建议人工检查")
    elif mojibake_rate > 0.005:
        cleanliness -= 6
        reasons.append("检测到少量疑似乱码")
    if ad_line_count > 30 or ad_line_rate > 0.05:
        cleanliness -= 10
        reasons.append("广告行较多，质量扣分")
    elif ad_line_count > 0:
        cleanliness -= min(5, ad_line_count * 0.5)
        reasons.append("检测到广告行")

    chapters = 25.0
    if chapter_count == 0:
        chapters -= 15
        reasons.append("未识别到章节")
    elif chapter_count >= 20:
        reasons.append("章节数较多，结构较完整")
    if duplicate_chapter_count:
        chapters -= min(8, duplicate_chapter_count * 2)
        reasons.append("检测到疑似重复章节")
    if missing_chapter_count:
        chapters -= min(8, missing_chapter_count * 1.5)
        reasons.append("检测到疑似缺章")
    if chapter_order_error_count:
        chapters -= min(6, chapter_order_error_count * 2)
        reasons.append("检测到章节顺序异常")

    metadata = 10.0
    if not title_norm:
        metadata -= 5
        reasons.append("未能识别标题")
    if not author_norm:
        metadata -= 2
        reasons.append("未能识别作者")

    trust = 10.0
    if re.search(r"www\.|http|笔趣阁|小说网|无弹窗|最新章节", file_name, re.I):
        trust -= 5
        reasons.append("文件名包含网站来源信息")
    if re.search(r"\(\d+\)|（\d+）|copy|副本", file_name, re.I):
        trust -= 2
        reasons.append("文件名像重复副本")

    score = max(0.0, min(100.0, integrity + cleanliness + chapters + metadata + trust))
    return QualityResult(round(score, 2), _level(score), reasons, truncated_risk)
