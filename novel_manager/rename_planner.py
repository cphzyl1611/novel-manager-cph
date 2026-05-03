from __future__ import annotations

import html
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .utils import file_ts, write_json

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

BAD_AUTHOR_KEYWORDS = ["txt下载", "http", "www", "=====", "最新章节", "下载", "小说网", "站"]
ABNORMAL_TARGET_PATTERNS = ["sxsy.org", "txt下载", "=====", "作者：", "作品作者：", ".txt.txt"]
MISSING_AUTHOR_VALUES = {"未知作者", "unknown", "none", "null", "无"}


def normalize_brackets(value: str) -> str:
    return (
        value.replace("（", "(")
        .replace("）", ")")
        .replace("【", "[")
        .replace("】", "]")
        .replace("「", "《")
        .replace("」", "》")
    )


def remove_source_prefixes(value: str) -> tuple[str, list[str]]:
    removed: list[str] = []
    text = value
    before = text
    text = re.sub(r"^\s*\[(?:sxsy\.org|www\.[^\]]+|https?://[^\]]+|[^\]]*(?:小说网|txt下载|笔趣阁|来源)[^\]]*)\]\s*", " ", text, flags=re.I)
    if text != before:
        removed.append("source_prefix")
    before = text
    text = re.sub(r"^\s*【(?:sxsy\.org|www\.[^】]+|https?://[^】]+|[^】]*(?:小说网|txt下载|笔趣阁|来源)[^】]*)】\s*", " ", text, flags=re.I)
    if text != before and "source_prefix" not in removed:
        removed.append("source_prefix")
    before = text
    text = re.sub(r"\b(?:www\.[\w.-]+|https?://\S+|txt下载|小说网)\b", " ", text, flags=re.I)
    if text != before:
        removed.append("source_prefix")
    return text, removed


def extract_statuses_from_filename_and_tags(book: dict[str, Any], tags: list[dict[str, Any]], *, max_status_count: int = 2) -> list[str]:
    text = " ".join(
        [
            str(book.get("file_name") or ""),
            str(book.get("title_raw") or ""),
            str(book.get("title_norm") or ""),
            " ".join(str(tag.get("name") or "") for tag in tags),
        ]
    )
    statuses: list[str] = []

    def add(status: str) -> None:
        if status not in statuses and len(statuses) < max_status_count:
            statuses.append(status)

    if re.search(r"未完结|连载", text):
        add("连载")
    elif re.search(r"无减全本|全本|完本|完结", text):
        add("完本")
    if re.search(r"精校|校对", text):
        add("精校")
    if re.search(r"修订", text):
        add("修订")
    if re.search(r"AI加料|加料", text, re.I):
        add("加料")
    if re.search(r"P站正式版本", text, re.I):
        add("正式版")
    return statuses


def extract_status_from_name_or_tags(book: dict[str, Any], tags: list[dict[str, Any]]) -> str | None:
    statuses = extract_statuses_from_filename_and_tags(book, tags)
    return " ".join(statuses) if statuses else None


def remove_chapter_ranges(value: str) -> tuple[str, list[str]]:
    removed: list[str] = []
    text = value
    patterns = [
        r"[\[(（]\s*\d+\s*[-_]\s*\d+\s*(?:章|卷)?(?:未完结|完结|连载)?\s*[\])）]",
        r"[\[(（]\s*\d+\s*卷\s*\d+\s*章\s*[\])）]",
        r"(?<!\d)\d+\s*[-_]\s*\d+\s*(?:章|卷)?(?:未完结|完结|连载)?",
        r"\b\d{2}_\d{2}\b",
        r"\b\d{2}_\d{2}\s*\+\s*重置\s*\d{2}_\d{2}\b",
        r"\b\d+\s+[-]?\s*\d+\b",
        r"\d+\s*卷\s*\d+\s*章",
        r"修订\s*\d+",
    ]
    for pattern in patterns:
        before = text
        text = re.sub(pattern, " ", text, flags=re.I)
        if text != before and "chapter_range" not in removed:
            removed.append("chapter_range")
    return text, removed


def remove_version_noise(value: str) -> tuple[str, list[str]]:
    removed: list[str] = []
    text = value
    patterns = [
        (r"P站正式版本", "status_word"),
        (r"AI加料|加料", "status_word"),
        (r"无减全本|全本|完本|完结|连载|未完结|精校|校对|修订|排版|重置", "status_word"),
        (r"(?i)\.txt(?:\.txt)*$", "duplicate_suffix"),
        (r"(?i)\bcopy\b|副本", "duplicate_suffix"),
        (r"[\[(（]\s*\d+\s*[\])）]", "duplicate_suffix"),
        (r"[\[(（]\s*\d+\s*$", "duplicate_suffix"),
    ]
    for pattern, label in patterns:
        before = text
        text = re.sub(pattern, " ", text, flags=re.I)
        if text != before and label not in removed:
            removed.append(label)
    return text, removed


def _extract_bracket_title(value: str) -> str | None:
    matches = re.findall(r"《([^》]{2,120})》", value)
    if matches:
        return matches[-1]
    match = re.search(r"【([^】]{2,120})】", value)
    if match:
        inner = match.group(1)
        if not re.search(r"sxsy\.org|www\.|http|小说网|txt下载|笔趣阁|来源", inner, re.I):
            return inner
    match = re.search(r"\[([^\]]{2,120})\]", value)
    if match:
        inner = match.group(1)
        if not re.search(r"sxsy\.org|www\.|http|小说网|txt下载|笔趣阁|来源", inner, re.I):
            return inner
    return None


def clean_title_for_filename(value: str | None) -> dict[str, Any]:
    raw = str(value or "")
    removed: list[str] = []
    risk_flags: list[str] = []
    text = raw.replace("\ufeff", " ").replace("\r", " ").replace("\n", " ")
    text, source_removed = remove_source_prefixes(text)
    removed.extend(source_removed)
    if source_removed:
        risk_flags.append("source_prefix_removed")

    bracket_title = _extract_bracket_title(text)
    if bracket_title:
        text = bracket_title
        removed.append("bracket_title_extracted")
    else:
        text = re.sub(r"(?:作品作者|作者)\s*[:：=]\s*.*$", " ", text)

    text, range_removed = remove_chapter_ranges(text)
    removed.extend(range_removed)
    if range_removed:
        risk_flags.append("chapter_range_removed")

    text, version_removed = remove_version_noise(text)
    removed.extend(version_removed)
    if "status_word" in version_removed:
        risk_flags.append("status_extracted")

    before = text
    text = re.sub(r"[《》【】\[\]（）()]", " ", text)
    text = re.sub(r"[<>\"/\\|?*\x00-\x1f]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ._-，,、")
    text = re.sub(r"[《》【】\[\]（）()]+$", "", text).strip(" ._-，,、")
    if text != before:
        removed.append("bracket_residue")
        risk_flags.append("bracket_residue_removed")
    if len(set(removed)) >= 3:
        risk_flags.append("title_cleaned_aggressively")
    return {
        "title_raw_source": raw,
        "title_cleaned": text,
        "removed_noise": sorted(set(removed)),
        "risk_flags": sorted(set(risk_flags)),
    }


def _clean_author_candidate(author: str | None) -> str:
    raw = re.sub(r"\s+", " ", str(author or "")).strip(" _-[]【】()（）")
    raw = re.sub(r"(?i)(?:\.txt)+$", "", raw).strip(" _-，,。.;；:：")
    raw = re.sub(r"(未完结|连载|完本|全本|完结|精校|校对)\s*$", "", raw).strip(" _-，,。.;；:：")
    raw = re.sub(r"\d+\s*[-_]\s*\d+\s*(?:章|卷)?\s*$", "", raw).strip(" _-，,。.;；:：")
    return raw


def validate_author(author: str | None) -> dict[str, Any]:
    raw = _clean_author_candidate(author)
    if not raw:
        return {"author": "", "valid": False, "suspicious": False, "reason": "missing"}
    if raw.strip().lower() in MISSING_AUTHOR_VALUES:
        return {"author": "", "valid": False, "suspicious": False, "reason": "missing placeholder"}
    if any(keyword.lower() in raw.lower() for keyword in BAD_AUTHOR_KEYWORDS):
        return {"author": "", "valid": False, "suspicious": True, "reason": "contains download/source text"}
    if re.search(r"(?i)\.txt", raw):
        return {"author": "", "valid": False, "suspicious": True, "reason": "contains txt suffix"}
    if re.search(r"\d+\s*[-_]\s*\d+", raw):
        return {"author": "", "valid": False, "suspicious": True, "reason": "contains chapter range"}
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", raw))
    if cjk_count > 20 or len(raw) > 30:
        return {"author": "", "valid": False, "suspicious": True, "reason": "too long"}
    return {"author": raw, "valid": True, "suspicious": False, "reason": ""}


def extract_author_from_filename(file_name: str) -> str:
    patterns = [
        r"(?:作品作者|作者)\s*[:：=]\s*([^\]\)）】]+)",
        r"\[(?:作品作者|作者)\s*[:：=]\s*([^\]]+)\]",
        r"【(?:作品作者|作者)\s*[:：=]\s*([^】]+)】",
    ]
    for pattern in patterns:
        match = re.search(pattern, file_name or "")
        if not match:
            continue
        candidate = re.split(r"\.txt|未完结|完结|连载|全本|完本|[_\]\)）】]", match.group(1), flags=re.I)[0]
        checked = validate_author(candidate)
        if checked["valid"]:
            return str(checked["author"])
    return ""


def _author_from_book(book: dict[str, Any]) -> dict[str, Any]:
    for key in ("author_norm", "author_raw"):
        checked = validate_author(book.get(key))
        if checked["valid"]:
            return {"author_raw_source": book.get(key), "author_used": checked["author"], "author_valid": True, "risk_flags": []}
        if checked["suspicious"]:
            return {"author_raw_source": book.get(key), "author_used": "", "author_valid": False, "risk_flags": ["author_suspicious"]}
    raw_name = str(book.get("file_name") or "")
    for pattern in [r"(?:作品作者|作者)\s*[:：=]\s*([^\]\)）】]+)", r"\[(?:作品作者|作者)\s*[:：=]\s*([^\]]+)\]"]:
        match = re.search(pattern, raw_name)
        if match:
            candidate = re.split(r"\.txt|未完结|完结|连载|全本|完本|[_\]\)）】]", match.group(1), flags=re.I)[0]
            checked = validate_author(candidate)
            if checked["valid"]:
                return {"author_raw_source": candidate, "author_used": checked["author"], "author_valid": True, "risk_flags": []}
            return {"author_raw_source": candidate, "author_used": "", "author_valid": False, "risk_flags": ["author_suspicious"]}
    return {"author_raw_source": "", "author_used": "", "author_valid": False, "risk_flags": ["author_missing"]}


def _title_from_book(book: dict[str, Any]) -> dict[str, Any]:
    candidates = [book.get("file_name"), book.get("title_norm"), book.get("title_raw"), Path(str(book.get("file_name") or "")).stem]
    best = {"title_raw_source": "", "title_cleaned": "", "removed_noise": [], "risk_flags": ["title_missing"]}
    for candidate in candidates:
        cleaned = clean_title_for_filename(candidate)
        if cleaned["title_cleaned"]:
            return cleaned
        best = cleaned
    return best


def sanitize_filename(name: str, *, max_length: int = 120) -> tuple[str, list[str]]:
    risks: list[str] = []
    value = str(name or "").replace("\ufeff", " ").replace("\r", " ").replace("\n", " ")
    before = value
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    if value != before:
        risks.append("unsafe_chars_removed")
    value = re.sub(r"\s+", " ", value).strip(" .")
    value = re.sub(r"(?i)(?:\.txt)+$", "", value).strip(" .")
    if not value:
        value = "untitled"
        risks.append("title_missing")
    stem = value
    if stem.upper() in WINDOWS_RESERVED_NAMES:
        stem = f"{stem}_file"
        risks.append("windows_reserved_name")
    max_stem = max(1, max_length - 4)
    if len(stem) > max_stem:
        stem = stem[:max_stem].rstrip(" .")
        risks.extend(["target_too_long", "target_truncated"])
    return f"{stem}.txt", risks


def build_target_name(title: str, author: str, statuses: list[str], *, style: str, unknown_author: str, include_unknown_author: bool) -> str:
    status_text = f" [{' '.join(statuses)}]" if statuses and style == "title-author-status" else ""
    if style == "title-only":
        return title
    if author:
        return f"{title} - {author}{status_text}"
    if include_unknown_author and style in {"title-author", "title-author-status"}:
        return f"{title} - {unknown_author}{status_text}"
    return f"{title}{status_text}"


def _target_abnormal(target: str) -> str | None:
    lowered = target.lower()
    for pattern in ABNORMAL_TARGET_PATTERNS:
        if pattern.lower() in lowered:
            return f"目标名仍包含异常片段：{pattern}"
    stem = re.sub(r"(?i)\.txt$", "", target)
    bracket_pairs = [("《", "》"), ("【", "】"), ("[", "]"), ("(", ")"), ("（", "）")]
    if any(stem.count(opening) != stem.count(closing) for opening, closing in bracket_pairs):
        return "目标名仍包含残缺括号"
    return None


def generate_target_filename(
    book: dict[str, Any],
    *,
    style: str,
    unknown_author: str = "未知作者",
    max_length: int = 120,
    tags: list[dict[str, Any]] | None = None,
    include_unknown_author: bool = False,
    max_status_count: int = 2,
) -> dict[str, Any]:
    tags = tags or []
    title = _title_from_book(book)
    author = _author_from_book(book)
    statuses = extract_statuses_from_filename_and_tags(book, tags, max_status_count=max_status_count)
    risks = list(title["risk_flags"]) + list(author["risk_flags"])
    if len(title["title_cleaned"]) < 2:
        risks.append("title_missing")
    if statuses:
        risks.append("status_extracted")
    base = build_target_name(
        title["title_cleaned"],
        author["author_used"],
        statuses,
        style=style,
        unknown_author=unknown_author,
        include_unknown_author=include_unknown_author,
    )
    target, sanitize_risks = sanitize_filename(base, max_length=max_length)
    risks.extend(sanitize_risks)
    abnormal = _target_abnormal(target)
    if abnormal:
        risks.append("manual_review_needed")
    return {
        "target_file_name": target,
        "title_used": title["title_cleaned"],
        "title_raw_source": title["title_raw_source"],
        "title_cleaned": title["title_cleaned"],
        "author_raw_source": author["author_raw_source"],
        "author_used": author["author_used"],
        "author_valid": author["author_valid"],
        "status_used": " ".join(statuses) if statuses else None,
        "statuses_used": statuses,
        "removed_noise": title["removed_noise"],
        "risk_flags": sorted(set(risks)),
        "abnormal_reason": abnormal,
    }


def _work_group_id(conn: sqlite3.Connection, book_id: int) -> int | None:
    try:
        row = conn.execute("SELECT work_group_id FROM book_group_members WHERE book_id = ? LIMIT 1", (book_id,)).fetchone()
    except sqlite3.Error:
        return None
    return int(row["work_group_id"]) if row else None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return row is not None


def _tags_for_books_readonly(conn: sqlite3.Connection, book_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not book_ids or not (_table_exists(conn, "tags") and _table_exists(conn, "book_tags")):
        return {book_id: [] for book_id in book_ids}
    placeholders = ",".join("?" for _ in book_ids)
    try:
        rows = conn.execute(
            f"""
            SELECT bt.book_id, t.name, t.category, bt.source, bt.confidence
            FROM book_tags bt
            JOIN tags t ON t.id = bt.tag_id
            WHERE bt.book_id IN ({placeholders})
            ORDER BY t.category, t.name
            """,
            book_ids,
        ).fetchall()
    except sqlite3.Error:
        return {book_id: [] for book_id in book_ids}
    result: dict[int, list[dict[str, Any]]] = {book_id: [] for book_id in book_ids}
    for row in rows:
        result.setdefault(int(row["book_id"]), []).append(dict(row))
    return result


def _reason(action: str, risks: list[str], item: dict[str, Any]) -> str:
    if item.get("abnormal_reason"):
        return str(item["abnormal_reason"])
    if "target_name_conflict" in risks:
        conflicts = item.get("conflict_with") or []
        if conflicts:
            ids = ", ".join(f"book_id={conflict['conflict_with_book_id']}" for conflict in conflicts[:3])
            return f"目标文件名与 {ids} 冲突"
        return "目标文件名存在冲突，需要人工确认"
    if "author_suspicious" in risks:
        return "作者字段疑似误提取，包含下载信息、章节范围或异常长度"
    if "title_missing" in risks:
        return "清洗后标题为空或过短"
    if "low_quality_book" in risks:
        return "书籍质量分较低，建议先检查内容再重命名"
    if "mojibake_risk" in risks:
        return "乱码率较高，建议先人工检查"
    if action == "no_change":
        return "目标文件名与当前文件名一致"
    return "根据清洗后的书名、作者和状态生成规范文件名"


def _base_query(area: str, query: str | None, limit: int | None) -> tuple[str, list[Any]]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    if area != "all":
        clauses.append("repo_area = ?")
        params.append(area)
    if query:
        like = f"%{query}%"
        clauses.append("(file_name LIKE ? OR title_raw LIKE ? OR title_norm LIKE ? OR author_raw LIKE ? OR author_norm LIKE ?)")
        params.extend([like, like, like, like, like])
    sql = f"SELECT * FROM books WHERE {' AND '.join(clauses)} ORDER BY repo_area, file_name, id"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return sql, params


def build_rename_plan(
    conn: sqlite3.Connection,
    repo: Path,
    *,
    area: str = "library",
    query: str | None = None,
    limit: int | None = None,
    include_unchanged: bool = False,
    style: str = "title-author-status",
    unknown_author: str = "未知作者",
    max_length: int = 120,
    include_unknown_author: bool = False,
    max_status_count: int = 2,
) -> dict[str, Any]:
    sql, params = _base_query(area, query, limit)
    books = [dict(row) for row in conn.execute(sql, params).fetchall()]
    tag_map = _tags_for_books_readonly(conn, [int(book["id"]) for book in books])
    current_paths = {str(row["current_path"]): dict(row) for row in conn.execute("SELECT id, current_path, file_name FROM books").fetchall()}
    suggestions: list[dict[str, Any]] = []
    target_index: dict[str, list[int]] = {}
    for book in books:
        tags = tag_map.get(int(book["id"]), [])
        generated = generate_target_filename(
            book,
            style=style,
            unknown_author=unknown_author,
            max_length=max_length,
            tags=tags,
            include_unknown_author=include_unknown_author,
            max_status_count=max_status_count,
        )
        risks = list(generated["risk_flags"])
        current_path = Path(str(book.get("current_path") or ""))
        target_path = current_path.with_name(generated["target_file_name"])
        if generated["target_file_name"] == book.get("file_name"):
            risks.append("target_same_as_current")
        if float(book.get("quality_score") or 0) < 60:
            risks.append("low_quality_book")
        if float(book.get("mojibake_rate") or 0) >= 0.005:
            risks.append("mojibake_risk")
        if int(book.get("ad_line_count") or 0) >= 50 or float(book.get("ad_line_rate") or 0) >= 0.02:
            risks.append("ad_heavy")
        work_group_id = _work_group_id(conn, int(book["id"]))
        if work_group_id is not None:
            risks.append("duplicate_book_group")
        conflict_with: list[dict[str, Any]] = []
        existing = current_paths.get(str(target_path))
        if existing and int(existing["id"]) != int(book["id"]):
            risks.append("target_name_conflict")
            conflict_with.append({"conflict_with_book_id": existing["id"], "conflict_with_path": existing["current_path"], "conflict_target_name": generated["target_file_name"]})
        target_index.setdefault(str(target_path), []).append(int(book["id"]))
        unique_risks = []
        for risk in risks:
            if risk not in unique_risks:
                unique_risks.append(risk)
        action = "rename_recommended"
        if "target_same_as_current" in unique_risks:
            action = "no_change"
        severe = {"title_missing", "target_name_conflict", "low_quality_book", "mojibake_risk", "author_suspicious"}
        if severe & set(unique_risks) or generated.get("abnormal_reason"):
            action = "manual_review"
            if "manual_review_needed" not in unique_risks:
                unique_risks.append("manual_review_needed")
        suggestion = {
            "book_id": book["id"],
            "repo_area": book.get("repo_area"),
            "current_file_name": book.get("file_name"),
            "current_path": book.get("current_path"),
            "target_file_name": generated["target_file_name"],
            "target_path_preview": str(target_path),
            "action": action,
            "title_used": generated["title_used"],
            "title_raw_source": generated["title_raw_source"],
            "title_cleaned": generated["title_cleaned"],
            "author_raw_source": generated["author_raw_source"],
            "author_used": generated["author_used"],
            "author_valid": generated["author_valid"],
            "status_used": generated["status_used"],
            "statuses_used": generated["statuses_used"],
            "style": style,
            "risk_flags": unique_risks,
            "removed_noise": generated["removed_noise"],
            "reason_summary": "",
            "quality_score": book.get("quality_score"),
            "quality_level": book.get("quality_level"),
            "chapter_count": book.get("chapter_count"),
            "ad_line_count": book.get("ad_line_count"),
            "mojibake_rate": book.get("mojibake_rate"),
            "tags": [tag["name"] for tag in tags],
            "work_group_id": work_group_id,
            "conflict_with": conflict_with,
            "abnormal_reason": generated.get("abnormal_reason"),
        }
        suggestion["reason_summary"] = _reason(action, unique_risks, suggestion)
        suggestions.append(suggestion)
    by_id = {int(item["book_id"]): item for item in suggestions}
    for target, ids in target_index.items():
        if len(ids) <= 1:
            continue
        for book_id in ids:
            item = by_id[book_id]
            if "target_name_conflict" not in item["risk_flags"]:
                item["risk_flags"].append("target_name_conflict")
            if "manual_review_needed" not in item["risk_flags"]:
                item["risk_flags"].append("manual_review_needed")
            item["action"] = "manual_review"
            item["conflict_with"].extend(
                {
                    "conflict_with_book_id": other_id,
                    "conflict_with_path": by_id[other_id]["current_path"],
                    "conflict_target_name": Path(target).name,
                }
                for other_id in ids
                if other_id != book_id
            )
            seen_conflicts: set[int] = set()
            deduped_conflicts = []
            for conflict in item["conflict_with"]:
                conflict_id = int(conflict["conflict_with_book_id"])
                if conflict_id in seen_conflicts:
                    continue
                seen_conflicts.add(conflict_id)
                deduped_conflicts.append(conflict)
            item["conflict_with"] = deduped_conflicts
            item["reason_summary"] = _reason("manual_review", item["risk_flags"], item)
    visible = suggestions if include_unchanged else [item for item in suggestions if item["action"] != "no_change"]
    stats = {
        "total_books": len(books),
        "rename_recommended": sum(1 for item in suggestions if item["action"] == "rename_recommended"),
        "no_change": sum(1 for item in suggestions if item["action"] == "no_change"),
        "manual_review": sum(1 for item in suggestions if item["action"] == "manual_review"),
        "target_name_conflict": sum(1 for item in suggestions if "target_name_conflict" in item["risk_flags"]),
        "author_missing": sum(1 for item in suggestions if "author_missing" in item["risk_flags"]),
        "author_suspicious": sum(1 for item in suggestions if "author_suspicious" in item["risk_flags"]),
        "title_missing": sum(1 for item in suggestions if "title_missing" in item["risk_flags"]),
        "low_quality_book": sum(1 for item in suggestions if "low_quality_book" in item["risk_flags"]),
        "target_truncated": sum(1 for item in suggestions if "target_truncated" in item["risk_flags"]),
    }
    return {
        "area": area,
        "query": query,
        "style": style,
        "unknown_author": unknown_author,
        "include_unknown_author": include_unknown_author,
        "max_status_count": max_status_count,
        "max_length": max_length,
        "include_unchanged": include_unchanged,
        "stats": stats,
        "suggestions": visible,
        "all_suggestions_count": len(suggestions),
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 批量重命名建议报告",
        "",
        "本报告只生成重命名计划，不会修改文件名。",
        "",
        "## 总览",
        "",
    ]
    for key, value in payload["stats"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## 建议列表", "", "| book_id | action | 当前文件名 | 建议文件名 | 风险 | 原因 |", "|---:|---|---|---|---|---|"])
    for item in payload["suggestions"]:
        lines.append(
            f"| {item['book_id']} | {item['action']} | `{item['current_file_name']}` | `{item['target_file_name']}` | {', '.join(item['risk_flags']) or '-'} | {item['reason_summary']} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _html(payload: dict[str, Any]) -> str:
    rows = []
    for item in payload["suggestions"]:
        cls = "conflict" if "target_name_conflict" in item["risk_flags"] else item["action"]
        conflicts = "; ".join(f"book_id={c['conflict_with_book_id']} {c['conflict_with_path']}" for c in item.get("conflict_with", []))
        rows.append(
            f"<tr class='{cls}'><td>{item['book_id']}</td><td>{html.escape(item['action'])}</td>"
            f"<td><code>{html.escape(str(item['current_file_name']))}</code></td>"
            f"<td><code>{html.escape(str(item['target_file_name']))}</code></td>"
            f"<td>{html.escape(str(item.get('title_cleaned') or ''))}</td>"
            f"<td>{html.escape(str(item.get('author_used') or ''))}</td>"
            f"<td>{html.escape(' '.join(item.get('statuses_used') or []))}</td>"
            f"<td>{html.escape(', '.join(item['removed_noise']))}</td>"
            f"<td>{html.escape(', '.join(item['risk_flags']))}</td>"
            f"<td>{html.escape(conflicts)}</td>"
            f"<td>{html.escape(item['reason_summary'])}</td></tr>"
        )
    stats = "".join(f"<li>{html.escape(k)}: {v}</li>" for k, v in payload["stats"].items())
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>批量重命名建议报告</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #202124; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: left; vertical-align: top; }}
th {{ background: #f6f8fa; }}
tr.rename_recommended {{ background: #f0fdf4; }}
tr.no_change {{ background: #f3f4f6; color: #6b7280; }}
tr.manual_review {{ background: #fffbeb; }}
tr.conflict {{ background: #fef2f2; }}
code {{ word-break: break-all; }}
</style>
</head>
<body>
<h1>批量重命名建议报告</h1>
<p><strong>本报告只生成重命名计划，不会修改文件名。</strong></p>
<h2>总览</h2><ul>{stats}</ul>
<table><thead><tr><th>book_id</th><th>action</th><th>当前文件名</th><th>建议文件名</th><th>清洗书名</th><th>作者</th><th>状态</th><th>移除噪声</th><th>风险</th><th>冲突对象</th><th>原因</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</body>
</html>
"""


def write_rename_plan_reports(repo: Path, payload: dict[str, Any]) -> tuple[Path, Path, Path]:
    ts = file_ts()
    out_dir = repo / "reports" / "rename"
    stem = f"rename_plan_{ts}"
    json_path = out_dir / f"{stem}.json"
    html_path = out_dir / f"{stem}.html"
    md_path = out_dir / f"{stem}.md"
    index = 1
    while json_path.exists() or html_path.exists() or md_path.exists():
        stem = f"rename_plan_{ts}_{index}"
        json_path = out_dir / f"{stem}.json"
        html_path = out_dir / f"{stem}.html"
        md_path = out_dir / f"{stem}.md"
        index += 1
    final_payload = {"generated_at": ts, **payload}
    write_json(json_path, final_payload)
    html_path.write_text(_html(final_payload), encoding="utf-8")
    md_path.write_text(_markdown(final_payload), encoding="utf-8")
    return html_path, json_path, md_path
