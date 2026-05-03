from __future__ import annotations

import sqlite3
from typing import Any

from .utils import now_ts


def _area_clause(area: str) -> tuple[str, list[Any]]:
    if area == "all":
        return "repo_area IN ('library', 'incoming')", []
    return "repo_area = ?", [area]


def _filename_dirty_penalty(name: str) -> int:
    dirty = ("www.", "http", "笔趣阁", "小说网", "无弹窗", "最新章节", "copy", "副本")
    return sum(1 for token in dirty if token.lower() in (name or "").lower())


def _rank_key(row: sqlite3.Row) -> tuple:
    return (
        float(row["quality_score"] or 0),
        1 if row["repo_area"] == "library" else 0,
        int(row["chapter_count"] or 0),
        int(row["char_count_clean"] or 0),
        -float(row["mojibake_rate"] or 0),
        -int(row["ad_line_count"] or 0),
        -_filename_dirty_penalty(row["file_name"] or ""),
        row["created_at"] or "",
    )


def _insert_group(conn: sqlite3.Connection, group_type: str, rows: list[sqlite3.Row]) -> dict[str, Any]:
    ranked = sorted(rows, key=_rank_key, reverse=True)
    keep = ranked[0]
    reason = f"推荐保留质量分更高的版本：book_id={keep['id']}，其余仅建议复核或移入 review_duplicates"
    conn.execute(
        """
        INSERT INTO duplicate_groups
        (group_type, confidence, recommended_keep_book_id, recommended_action, reason_summary, created_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (group_type, 1.0, keep["id"], "review", reason, now_ts(), "open"),
    )
    group_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    members = []
    for row in ranked:
        role = "keep" if row["id"] == keep["id"] else "archive_candidate"
        member_reason = "推荐保留" if role == "keep" else "精确重复，建议移动到 review_duplicates 后人工确认"
        conn.execute(
            """
            INSERT INTO duplicate_group_members
            (duplicate_group_id, book_id, similarity_score, quality_score, suggested_role, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (group_id, row["id"], 1.0, row["quality_score"], role, member_reason),
        )
        members.append({"book": dict(row), "suggested_role": role, "reason": member_reason, "similarity_score": 1.0})
    return {
        "id": group_id,
        "group_type": group_type,
        "confidence": 1.0,
        "recommended_keep_book_id": keep["id"],
        "recommended_action": "review",
        "reason_summary": reason,
        "members": members,
    }


def find_exact_duplicates(conn: sqlite3.Connection, area: str) -> list[dict[str, Any]]:
    clause, params = _area_clause(area)
    conn.execute("DELETE FROM duplicate_group_members")
    conn.execute("DELETE FROM duplicate_groups")
    groups: list[dict[str, Any]] = []

    raw_hashes = conn.execute(
        f"""
        SELECT raw_sha256 FROM books
        WHERE {clause} AND status = 'active' AND raw_sha256 IS NOT NULL
        GROUP BY raw_sha256 HAVING COUNT(*) > 1
        """,
        params,
    ).fetchall()
    raw_duplicate_ids: set[int] = set()
    for item in raw_hashes:
        rows = conn.execute(
            f"SELECT * FROM books WHERE {clause} AND raw_sha256 = ? ORDER BY id",
            params + [item["raw_sha256"]],
        ).fetchall()
        raw_duplicate_ids.update(int(row["id"]) for row in rows)
        groups.append(_insert_group(conn, "raw_exact", rows))

    clean_hashes = conn.execute(
        f"""
        SELECT clean_sha256 FROM books
        WHERE {clause} AND status = 'active' AND clean_sha256 IS NOT NULL
        GROUP BY clean_sha256 HAVING COUNT(*) > 1
        """,
        params,
    ).fetchall()
    for item in clean_hashes:
        rows = conn.execute(
            f"SELECT * FROM books WHERE {clause} AND clean_sha256 = ? ORDER BY id",
            params + [item["clean_sha256"]],
        ).fetchall()
        raw_values = {row["raw_sha256"] for row in rows}
        if len(raw_values) <= 1:
            continue
        groups.append(_insert_group(conn, "clean_exact", rows))

    conn.commit()
    return groups
