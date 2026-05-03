from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from rapidfuzz import fuzz

from .utils import ensure_dir, file_ts, now_ts, write_json


def migrate_work_group_schema(conn: sqlite3.Connection) -> None:
    def columns(table: str) -> set[str]:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    wg_cols = columns("work_groups")
    wg_add = {
        "canonical_title": "TEXT",
        "canonical_author": "TEXT",
        "primary_book_id": "INTEGER",
        "group_confidence": "REAL",
        "group_source": "TEXT",
        "description": "TEXT",
        "updated_at": "TEXT",
    }
    for name, ddl in wg_add.items():
        if name not in wg_cols:
            conn.execute(f"ALTER TABLE work_groups ADD COLUMN {name} {ddl}")

    bgm_cols = columns("book_group_members")
    bgm_add = {
        "confidence": "REAL",
        "source": "TEXT",
        "note": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    }
    for name, ddl in bgm_add.items():
        if name not in bgm_cols:
            conn.execute(f"ALTER TABLE book_group_members ADD COLUMN {name} {ddl}")
    conn.commit()


def _env() -> Environment:
    template_dir = Path(__file__).resolve().parent.parent / "templates"
    return Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "xml"]))


def _area_clause(area: str) -> tuple[str, list[Any]]:
    if area == "all":
        return "repo_area IN ('library', 'incoming', 'review_duplicates')", []
    return "repo_area = ?", [area]


def load_books(conn: sqlite3.Connection, area: str = "all", limit: int | None = None) -> list[dict[str, Any]]:
    clause, params = _area_clause(area)
    sql = f"SELECT * FROM books WHERE status = 'active' AND {clause} ORDER BY id ASC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _dirty_penalty(book: dict[str, Any]) -> int:
    name = (book.get("file_name") or "").lower()
    return sum(1 for token in ("www.", "http", "笔趣阁", "小说网", "无弹窗", "最新章节", "copy", "副本") if token in name)


def primary_rank(book: dict[str, Any]) -> tuple:
    return (
        1 if book.get("repo_area") == "library" else 0,
        float(book.get("quality_score") or 0),
        int(book.get("chapter_count") or 0),
        int(book.get("char_count_clean") or 0),
        -int(book.get("ad_line_count") or 0),
        -float(book.get("mojibake_rate") or 0),
        -_dirty_penalty(book),
        book.get("updated_at") or "",
    )


def choose_primary(books: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(books, key=primary_rank, reverse=True)[0]


def _role_for_member(book: dict[str, Any], primary: dict[str, Any], confidence: float, source: str, manual_review: bool) -> tuple[str, str]:
    if manual_review:
        return "manual_review", "置信不足或存在作者冲突，建议人工复核"
    if book["id"] == primary["id"]:
        return "primary", "推荐主版本"
    if source in {"raw_sha256", "clean_sha256", "duplicate_groups"}:
        return "duplicate", "精确重复或清洗后完全一致"
    q_gap = float(primary.get("quality_score") or 0) - float(book.get("quality_score") or 0)
    c_gap = int(primary.get("chapter_count") or 0) - int(book.get("chapter_count") or 0)
    char_gap = int(primary.get("char_count_clean") or 0) - int(book.get("char_count_clean") or 0)
    if q_gap >= 20 or int(book.get("ad_line_count") or 0) > int(primary.get("ad_line_count") or 0) + 20:
        return "bad_version", "质量明显低或广告更多"
    if c_gap >= 5 or char_gap > max(10000, int(primary.get("char_count_clean") or 0) * 0.2):
        return "old_version", "章节或字数明显少，可能是旧版"
    return "version", "同一作品的普通版本"


def _candidate_from_books(
    candidate_id: int,
    books: list[dict[str, Any]],
    confidence: float,
    source: str,
    reason: str,
    *,
    force_manual: bool = False,
) -> dict[str, Any]:
    authors = {book.get("author_norm") for book in books if book.get("author_norm")}
    author_conflict = len(authors) > 1
    manual_review = force_manual or author_conflict or confidence < 0.85
    confidence = min(confidence, 0.65) if author_conflict else confidence
    primary = choose_primary(books)
    canonical_title = primary.get("title_norm") or primary.get("title_raw") or primary.get("file_name") or ""
    canonical_author = primary.get("author_norm") or primary.get("author_raw") or ""
    max_chapters = max(int(book.get("chapter_count") or 0) for book in books)
    min_chapters = min(int(book.get("chapter_count") or 0) for book in books)
    max_quality = max(float(book.get("quality_score") or 0) for book in books)
    min_quality = min(float(book.get("quality_score") or 0) for book in books)
    risks: list[str] = []
    if author_conflict:
        risks.append("作者冲突")
    if manual_review:
        risks.append("低置信")
    if max_quality - min_quality >= 20:
        risks.append("质量差异大")
    if max_chapters - min_chapters >= 5:
        risks.append("章节数差异大")
    members = []
    for book in sorted(books, key=primary_rank, reverse=True):
        role, member_reason = _role_for_member(book, primary, confidence, source, manual_review)
        if role == "old_version":
            risks.append("可能是旧版")
        if role == "bad_version":
            risks.append("可能是广告版")
        members.append(
            {
                "book_id": book["id"],
                "file_name": book.get("file_name"),
                "current_path": book.get("current_path"),
                "role": role,
                "confidence": confidence,
                "source": source,
                "quality_score": book.get("quality_score"),
                "quality_level": book.get("quality_level"),
                "chapter_count": book.get("chapter_count"),
                "char_count_clean": book.get("char_count_clean"),
                "ad_line_count": book.get("ad_line_count"),
                "mojibake_rate": book.get("mojibake_rate"),
                "member_reason": member_reason,
            }
        )
    return {
        "candidate_group_id": candidate_id,
        "canonical_title": canonical_title,
        "canonical_author": canonical_author,
        "group_confidence": round(confidence, 4),
        "group_reason": reason,
        "group_source": source,
        "recommended_primary_book_id": primary["id"],
        "recommended_primary_file": primary.get("current_path"),
        "members": members,
        "auto_apply": (not manual_review) and confidence >= 0.85,
        "manual_review": manual_review,
        "risks": sorted(set(risks)),
    }


def _add_group(raw_groups: list[tuple[set[int], float, str, str, bool]], ids: set[int], confidence: float, source: str, reason: str, manual: bool = False) -> None:
    if len(ids) >= 2:
        raw_groups.append((ids, confidence, source, reason, manual))


def generate_group_candidates(
    conn: sqlite3.Connection,
    *,
    area: str = "all",
    min_confidence: float = 0.85,
    include_low_confidence: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    books = load_books(conn, area, limit)
    by_id = {book["id"]: book for book in books}
    raw_groups: list[tuple[set[int], float, str, str, bool]] = []

    for key in ("clean_sha256", "raw_sha256"):
        grouped: dict[str, set[int]] = {}
        for book in books:
            value = book.get(key)
            if value:
                grouped.setdefault(value, set()).add(book["id"])
        for ids in grouped.values():
            reason = "clean_sha256 完全相同" if key == "clean_sha256" else "raw_sha256 完全相同"
            _add_group(raw_groups, ids, 1.0, key, reason)

    dup_rows = conn.execute(
        """
        SELECT dg.id, dg.group_type, dg.confidence, dgm.book_id
        FROM duplicate_groups dg
        JOIN duplicate_group_members dgm ON dgm.duplicate_group_id = dg.id
        WHERE dg.group_type IN ('raw_exact', 'clean_exact')
        """
    ).fetchall()
    dup_map: dict[int, tuple[set[int], float]] = {}
    for row in dup_rows:
        if row["book_id"] in by_id:
            ids, conf = dup_map.setdefault(row["id"], (set(), float(row["confidence"] or 1.0)))
            ids.add(row["book_id"])
    for ids, conf in dup_map.values():
        _add_group(raw_groups, ids, conf, "duplicate_groups", "来自精确重复检测结果")

    title_map: dict[str, list[dict[str, Any]]] = {}
    for book in books:
        title = book.get("title_norm")
        if title:
            title_map.setdefault(title, []).append(book)
    for title_books in title_map.values():
        if len(title_books) < 2:
            continue
        author_values = {book.get("author_norm") for book in title_books if book.get("author_norm")}
        has_missing_author = any(not book.get("author_norm") for book in title_books)
        if len(author_values) > 1:
            _add_group(raw_groups, {book["id"] for book in title_books}, 0.65, "title_author_conflict", "标题一致但作者冲突", True)
        elif has_missing_author:
            _add_group(raw_groups, {book["id"] for book in title_books}, 0.88, "title_missing_author", "标题一致，作者缺失，建议人工复核", True)
        else:
            _add_group(raw_groups, {book["id"] for book in title_books}, 0.95, "title_author_exact", "标题和作者规范化后完全一致")

    for i, left in enumerate(books):
        for right in books[i + 1 :]:
            if not left.get("title_norm") or not right.get("title_norm"):
                continue
            if left.get("title_norm") == right.get("title_norm"):
                continue
            if left.get("author_norm") and left.get("author_norm") == right.get("author_norm"):
                similarity = fuzz.ratio(left["title_norm"], right["title_norm"]) / 100
                if similarity >= 0.95:
                    _add_group(raw_groups, {left["id"], right["id"]}, 0.86, "title_similarity", "标题高度相似")

    # Merge overlapping high-confidence exact signals; keep conservative metadata.
    unique: dict[tuple[int, ...], tuple[float, str, str, bool]] = {}
    for ids, conf, source, reason, manual in raw_groups:
        key = tuple(sorted(ids))
        old = unique.get(key)
        if old is None or conf > old[0]:
            unique[key] = (conf, source, reason, manual)

    candidates = []
    for idx, (ids_key, (conf, source, reason, manual)) in enumerate(unique.items(), 1):
        if conf < min_confidence and not include_low_confidence:
            continue
        books_for_group = [by_id[book_id] for book_id in ids_key if book_id in by_id]
        if len(books_for_group) < 2:
            continue
        candidates.append(_candidate_from_books(idx, books_for_group, conf, source, reason, force_manual=manual))
    return candidates


def _insert_operation(conn: sqlite3.Connection, operation_type: str, reason: str) -> None:
    conn.execute(
        """
        INSERT INTO operations
        (operation_type, status, reason, created_at, applied_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (operation_type, "success", reason, now_ts(), now_ts()),
    )
    conn.commit()


def apply_group_candidates(conn: sqlite3.Connection, candidates: list[dict[str, Any]], *, min_confidence: float = 0.85) -> list[int]:
    migrate_work_group_schema(conn)
    applied: list[int] = []
    for candidate in candidates:
        if candidate.get("manual_review") or float(candidate.get("group_confidence") or 0) < min_confidence:
            continue
        now = now_ts()
        conn.execute(
            """
            INSERT INTO work_groups
            (canonical_title, canonical_author, primary_book_id, group_confidence, group_source, description, created_at, updated_at, title_norm, author_norm, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate["canonical_title"],
                candidate["canonical_author"],
                candidate["recommended_primary_book_id"],
                candidate["group_confidence"],
                candidate["group_source"],
                candidate["group_reason"],
                now,
                now,
                candidate["canonical_title"],
                candidate["canonical_author"],
                "active",
            ),
        )
        group_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        for member in candidate["members"]:
            conn.execute(
                """
                INSERT INTO book_group_members
                (work_group_id, book_id, role, confidence, source, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group_id,
                    member["book_id"],
                    member["role"],
                    member["confidence"],
                    member["source"],
                    member["member_reason"],
                    now,
                    now,
                ),
            )
        applied.append(group_id)
    conn.commit()
    if applied:
        _insert_operation(conn, "group_books_apply", f"applied work_groups: {applied}")
    return applied


def generate_group_report(repo: Path, candidates: list[dict[str, Any]], applied_group_ids: list[int] | None = None) -> tuple[Path, Path]:
    ts = file_ts()
    out_dir = repo / "reports" / "group"
    ensure_dir(out_dir)
    payload = {"generated_at": ts, "candidates": candidates, "applied_group_ids": applied_group_ids or []}
    json_path = out_dir / f"group_report_{ts}.json"
    html_path = out_dir / f"group_report_{ts}.html"
    write_json(json_path, payload)
    html_path.write_text(_env().get_template("group_report.html.j2").render(**payload), encoding="utf-8")
    return html_path, json_path


def group_books(
    conn: sqlite3.Connection,
    repo: Path,
    *,
    area: str = "all",
    apply: bool = False,
    dry_run: bool = False,
    min_confidence: float = 0.85,
    include_low_confidence: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    candidates = generate_group_candidates(
        conn,
        area=area,
        min_confidence=min_confidence,
        include_low_confidence=include_low_confidence,
        limit=limit,
    )
    applied = [] if dry_run or not apply else apply_group_candidates(conn, candidates, min_confidence=min_confidence)
    html_path, json_path = generate_group_report(repo, candidates, applied)
    return {"candidates": candidates, "applied_group_ids": applied, "html_path": html_path, "json_path": json_path}


def list_groups(conn: sqlite3.Connection, *, limit: int = 50, query: str | None = None, sort: str = "updated_at", descending: bool = True, include_empty: bool = False) -> list[dict[str, Any]]:
    migrate_work_group_schema(conn)
    sort_cols = {"updated_at": "wg.updated_at", "member_count": "member_count", "group_confidence": "wg.group_confidence", "title": "wg.canonical_title"}
    params: list[Any] = []
    where = ["COALESCE(wg.status, 'active') != 'merged'"]
    if query:
        where.append("(wg.canonical_title LIKE ? OR wg.canonical_author LIKE ?)")
        params.extend([f"%{query}%", f"%{query}%"])
    having = "" if include_empty else "HAVING member_count > 0"
    direction = "DESC" if descending else "ASC"
    rows = conn.execute(
        f"""
        SELECT wg.id AS group_id, wg.canonical_title, wg.canonical_author, wg.primary_book_id,
               COUNT(bgm.id) AS member_count, wg.group_confidence, wg.group_source, wg.updated_at
        FROM work_groups wg
        LEFT JOIN book_group_members bgm ON bgm.work_group_id = wg.id
        WHERE {' AND '.join(where)}
        GROUP BY wg.id
        {having}
        ORDER BY {sort_cols.get(sort, 'wg.updated_at')} {direction}, wg.id {direction}
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()
    return [dict(row) for row in rows]


def inspect_group(conn: sqlite3.Connection, group_id: int) -> dict[str, Any]:
    migrate_work_group_schema(conn)
    group = conn.execute("SELECT * FROM work_groups WHERE id = ?", (group_id,)).fetchone()
    if not group:
        return {"status": "not_found", "message": "没有找到指定作品组。"}
    members = conn.execute(
        """
        SELECT bgm.book_id, bgm.role, bgm.confidence, bgm.source, bgm.note,
               b.file_name, b.current_path, b.quality_score, b.quality_level, b.chapter_count,
               b.char_count_clean, b.ad_line_count, b.mojibake_rate, b.repo_area
        FROM book_group_members bgm
        JOIN books b ON b.id = bgm.book_id
        WHERE bgm.work_group_id = ?
        ORDER BY CASE bgm.role WHEN 'primary' THEN 0 ELSE 1 END, b.quality_score DESC
        """,
        (group_id,),
    ).fetchall()
    member_dicts = [dict(row) for row in members]
    primary_id = group["primary_book_id"]
    primary = next((m for m in member_dicts if m["book_id"] == primary_id), None)
    reasons = []
    if primary:
        reasons.append("主版本按 library 优先、质量分、章节数、字数、广告行和乱码率综合推荐或人工指定。")
        for member in member_dicts:
            if member["book_id"] == primary_id:
                continue
            diffs = []
            if float(member.get("quality_score") or 0) < float(primary.get("quality_score") or 0):
                diffs.append("质量分更低")
            if int(member.get("chapter_count") or 0) < int(primary.get("chapter_count") or 0):
                diffs.append("章节更少")
            if int(member.get("ad_line_count") or 0) > int(primary.get("ad_line_count") or 0):
                diffs.append("广告更多")
            reasons.append(f"book_id={member['book_id']}：" + ("，".join(diffs) if diffs else "与主版本差异较小"))
    return {"status": "ok", "group": dict(group), "members": member_dicts, "primary_reasons": reasons}


def set_primary(conn: sqlite3.Connection, group_id: int, book_id: int) -> dict[str, Any]:
    migrate_work_group_schema(conn)
    exists = conn.execute("SELECT 1 FROM book_group_members WHERE work_group_id = ? AND book_id = ?", (group_id, book_id)).fetchone()
    if not exists:
        return {"status": "error", "message": "book_id 不属于该作品组，已拒绝设置。"}
    now = now_ts()
    conn.execute("UPDATE work_groups SET primary_book_id = ?, updated_at = ? WHERE id = ?", (book_id, now, group_id))
    conn.execute("UPDATE book_group_members SET role = CASE WHEN book_id = ? THEN 'primary' ELSE 'version' END, updated_at = ? WHERE work_group_id = ?", (book_id, now, group_id))
    conn.commit()
    _insert_operation(conn, "set_primary", f"group_id={group_id}, book_id={book_id}")
    return {"status": "ok", "message": "主版本已更新。"}


def merge_groups(conn: sqlite3.Connection, source_group_id: int, target_group_id: int) -> dict[str, Any]:
    migrate_work_group_schema(conn)
    source = conn.execute("SELECT * FROM work_groups WHERE id = ?", (source_group_id,)).fetchone()
    target = conn.execute("SELECT * FROM work_groups WHERE id = ?", (target_group_id,)).fetchone()
    if not source or not target:
        return {"status": "error", "message": "source 或 target 作品组不存在。"}
    now = now_ts()
    conn.execute("UPDATE book_group_members SET work_group_id = ?, role = CASE WHEN role = 'primary' THEN 'version' ELSE role END, updated_at = ? WHERE work_group_id = ?", (target_group_id, now, source_group_id))
    conn.execute("UPDATE work_groups SET status = 'merged', description = COALESCE(description, '') || ?, updated_at = ? WHERE id = ?", (f" merged into {target_group_id}", now, source_group_id))
    conn.execute("UPDATE work_groups SET updated_at = ? WHERE id = ?", (now, target_group_id))
    conn.commit()
    _insert_operation(conn, "merge_groups", f"source_group_id={source_group_id}, target_group_id={target_group_id}")
    return {"status": "ok", "message": "作品组已合并；如主版本不合适，可使用 set-primary 修改。"}


def _book_to_new_group(conn: sqlite3.Connection, book_id: int) -> int:
    book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if not book:
        raise ValueError("book not found")
    now = now_ts()
    conn.execute(
        """
        INSERT INTO work_groups
        (canonical_title, canonical_author, primary_book_id, group_confidence, group_source, description, created_at, updated_at, title_norm, author_norm, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            book["title_norm"] or book["title_raw"] or book["file_name"],
            book["author_norm"] or book["author_raw"],
            book_id,
            1.0,
            "manual_split",
            "split from existing group",
            now,
            now,
            book["title_norm"],
            book["author_norm"],
            "active",
        ),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def split_group(conn: sqlite3.Connection, book_id: int) -> dict[str, Any]:
    migrate_work_group_schema(conn)
    member = conn.execute("SELECT * FROM book_group_members WHERE book_id = ? ORDER BY id DESC LIMIT 1", (book_id,)).fetchone()
    if not member:
        return {"status": "error", "message": "该 book 不属于任何作品组。"}
    old_group_id = member["work_group_id"]
    new_group_id = _book_to_new_group(conn, book_id)
    now = now_ts()
    conn.execute("UPDATE book_group_members SET work_group_id = ?, role = 'primary', source = 'manual_split', note = 'split into new group', updated_at = ? WHERE id = ?", (new_group_id, now, member["id"]))
    old_group = conn.execute("SELECT primary_book_id FROM work_groups WHERE id = ?", (old_group_id,)).fetchone()
    if old_group and old_group["primary_book_id"] == book_id:
        rows = conn.execute(
            """
            SELECT b.* FROM book_group_members bgm
            JOIN books b ON b.id = bgm.book_id
            WHERE bgm.work_group_id = ?
            """,
            (old_group_id,),
        ).fetchall()
        remaining = [dict(row) for row in rows]
        if remaining:
            primary = choose_primary(remaining)
            conn.execute("UPDATE work_groups SET primary_book_id = ?, updated_at = ? WHERE id = ?", (primary["id"], now, old_group_id))
            conn.execute("UPDATE book_group_members SET role = CASE WHEN book_id = ? THEN 'primary' ELSE 'version' END, updated_at = ? WHERE work_group_id = ?", (primary["id"], now, old_group_id))
    conn.commit()
    _insert_operation(conn, "split_group", f"book_id={book_id}, old_group_id={old_group_id}, new_group_id={new_group_id}")
    return {"status": "ok", "old_group_id": old_group_id, "new_group_id": new_group_id, "message": "已拆分到新的作品组。"}
