from __future__ import annotations

import re
from dataclasses import dataclass

from .fingerprint import normalize_chapter_title, sha256_text


CN_NUM = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


@dataclass
class ChapterParseResult:
    chapters: list[dict]
    duplicate_chapter_count: int
    missing_chapter_count: int
    chapter_order_error_count: int


CHAPTER_RE = re.compile(
    r"^\s*(?P<title>("
    r"第\s*(?P<num>\d{1,5})\s*[章节回卷部集].*|"
    r"第\s*(?P<cn>[零〇一二两三四五六七八九十百千万]{1,12})\s*[章节回].*|"
    r"(?:第\s*)?[零〇一二两三四五六七八九十百千万]{1,8}\s*卷.*|"
    r"卷\s*\d+.*|"
    r"序章.*|楔子.*|番外.*|"
    r"Chapter\s*(?P<en>\d{1,5}).*"
    r"))\s*$",
    re.IGNORECASE,
)


def chinese_to_int(value: str) -> int | None:
    if not value:
        return None
    total = 0
    section = 0
    number = 0
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    for ch in value:
        if ch in CN_NUM:
            number = CN_NUM[ch]
        elif ch in units:
            unit = units[ch]
            if unit == 10000:
                section = (section + (number or 1)) * unit
                total += section
                section = 0
            else:
                section += (number or 1) * unit
            number = 0
        else:
            return None
    return total + section + number


def _chapter_type(title: str) -> str:
    lowered = title.lower()
    if "番外" in title:
        return "extra"
    if "序章" in title or "楔子" in title:
        return "prologue"
    if "卷" in title and "章" not in title:
        return "volume"
    if lowered.startswith("chapter"):
        return "chapter"
    return "chapter"


def parse_chapters(text: str) -> ChapterParseResult:
    lines = text.splitlines(keepends=True)
    matches: list[dict] = []
    offset = 0
    for line in lines:
        stripped = line.strip()
        match = CHAPTER_RE.match(stripped)
        if match:
            num: int | None = None
            if match.groupdict().get("num"):
                num = int(match.group("num"))
            elif match.groupdict().get("en"):
                num = int(match.group("en"))
            elif match.groupdict().get("cn"):
                num = chinese_to_int(match.group("cn"))
            matches.append({"title": stripped, "start": offset, "chapter_no": num})
        offset += len(line)

    chapters: list[dict] = []
    seen_titles: set[str] = set()
    duplicate_count = 0
    order_errors = 0
    missing_count = 0
    last_no: int | None = None
    for idx, item in enumerate(matches):
        start = item["start"]
        end = matches[idx + 1]["start"] if idx + 1 < len(matches) else len(text)
        body = text[start:end]
        title_norm = normalize_chapter_title(item["title"])
        duplicate = title_norm in seen_titles
        if duplicate:
            duplicate_count += 1
        seen_titles.add(title_norm)
        chapter_no = item["chapter_no"]
        order_status = "unknown"
        is_missing = 0
        if chapter_no is not None:
            order_status = "ok"
            if last_no is not None:
                if chapter_no < last_no:
                    order_status = "reversed"
                    order_errors += 1
                elif chapter_no > last_no + 1:
                    is_missing = 1
                    missing_count += chapter_no - last_no - 1
                    order_status = "gap"
            last_no = chapter_no
        chapters.append(
            {
                "chapter_index": idx + 1,
                "chapter_no": chapter_no,
                "chapter_type": _chapter_type(item["title"]),
                "title_raw": item["title"],
                "title_norm": title_norm,
                "start_offset": start,
                "end_offset": end,
                "char_count": len(body),
                "body_clean_sha256": sha256_text(body.strip()),
                "is_duplicate_suspect": 1 if duplicate else 0,
                "is_missing_suspect": is_missing,
                "order_status": order_status,
            }
        )
    return ChapterParseResult(chapters, duplicate_count, missing_count, order_errors)
