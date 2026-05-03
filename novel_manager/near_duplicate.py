from __future__ import annotations

import hashlib
import itertools
import sqlite3
from pathlib import Path
from typing import Any, Callable

from rapidfuzz import fuzz

from .fingerprint import normalize_title
from .scanner import detect_and_decode
from .text_cleaner import clean_text
from .utils import now_ts
from .work_groups import apply_group_candidates, migrate_work_group_schema


TextLookup = Callable[[dict[str, Any]], str]


def _tokens(text: str) -> list[str]:
    compact = "".join(ch for ch in text.lower() if not ch.isspace())
    if not compact:
        return []
    tokens: list[str] = []
    for n in (2, 3):
        if len(compact) >= n:
            tokens.extend(compact[i : i + n] for i in range(len(compact) - n + 1))
    return tokens or [compact]


def _hash64(value: str) -> int:
    return int.from_bytes(hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big")


def text_simhash(text: str) -> int:
    tokens = _tokens(text)
    if not tokens:
        return 0
    weights = [0] * 64
    for token in tokens:
        h = _hash64(token)
        for i in range(64):
            weights[i] += 1 if (h >> i) & 1 else -1
    result = 0
    for i, weight in enumerate(weights):
        if weight >= 0:
            result |= 1 << i
    return result


def simhash_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def simhash_similarity(a: int, b: int) -> float:
    return max(0.0, min(1.0, 1.0 - simhash_distance(a, b) / 64.0))


def chunk_hashes(text: str, chunk_size: int = 1200, step: int = 1200) -> set[str]:
    if not text:
        return set()
    if chunk_size <= 0 or step <= 0:
        raise ValueError("chunk_size and step must be positive")
    chunks = set()
    for start in range(0, len(text), step):
        chunk = text[start : start + chunk_size]
        if chunk:
            chunks.add(hashlib.sha256(chunk.encode("utf-8")).hexdigest())
        if start + chunk_size >= len(text):
            break
    return chunks


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    if not set_a and not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def chapter_title_overlap(conn: sqlite3.Connection, book_a: int, book_b: int) -> float:
    def titles(book_id: int) -> set[str]:
        rows = conn.execute("SELECT title_norm FROM chapters WHERE book_id = ?", (book_id,)).fetchall()
        return {row["title_norm"] for row in rows if row["title_norm"]}

    return jaccard_similarity(titles(book_a), titles(book_b))


def title_similarity(title_a: str | None, title_b: str | None) -> float:
    a = normalize_title(title_a or "")
    b = normalize_title(title_b or "")
    if not a or not b:
        return 0.0
    return fuzz.ratio(a, b) / 100.0


def author_similarity(author_a: str | None, author_b: str | None) -> float:
    a = (author_a or "").strip()
    b = (author_b or "").strip()
    if not a and not b:
        return 0.5
    if not a or not b:
        return 0.5
    return 1.0 if a == b else 0.0


def length_reasonableness(book_a: dict[str, Any], book_b: dict[str, Any]) -> float:
    a = int(book_a.get("char_count_clean") or 0)
    b = int(book_b.get("char_count_clean") or 0)
    if a <= 0 or b <= 0:
        return 0.0
    if a < 1000 and b < 1000:
        return 0.3
    ratio = max(a, b) / max(1, min(a, b))
    if ratio <= 1.2:
        return 1.0
    if ratio <= 2.0:
        return 0.75
    if ratio <= 3.0:
        return 0.45
    return 0.15


def _chapter_titles(conn: sqlite3.Connection, book_id: int) -> set[str]:
    rows = conn.execute("SELECT title_norm FROM chapters WHERE book_id = ?", (book_id,)).fetchall()
    return {row["title_norm"] for row in rows if row["title_norm"]}


def _read_clean_text(book: dict[str, Any]) -> str:
    path = Path(book.get("current_path") or "")
    if not path.exists():
        return ""
    raw = path.read_bytes()
    text, _, _, _ = detect_and_decode(raw)
    cleaned, _ = clean_text(text)
    return cleaned


def _rank_key(book: dict[str, Any]) -> tuple:
    return (
        1 if book.get("repo_area") == "library" else 0,
        float(book.get("quality_score") or 0),
        int(book.get("chapter_count") or 0),
        int(book.get("char_count_clean") or 0),
        -int(book.get("ad_line_count") or 0),
        -float(book.get("mojibake_rate") or 0),
        book.get("updated_at") or "",
    )


def _confidence_level(score: float, high_confidence: float) -> str:
    if score >= high_confidence:
        return "high_confidence"
    if score >= 0.82:
        return "probable_duplicate"
    return "suspicious"


def _member_role(book: dict[str, Any], primary: dict[str, Any], manual_review: bool) -> tuple[str, str]:
    if book["id"] == primary["id"]:
        return "keep", "推荐保留为对比基准版本"
    if manual_review:
        return "review", "近似重复候选，需要人工复核"
    return "archive_candidate", "高置信近似重复，可人工确认后进入 review_duplicates"


def _same_work_groups(conn: sqlite3.Connection, book_a: int, book_b: int) -> tuple[bool, bool]:
    try:
        migrate_work_group_schema(conn)
        rows = conn.execute(
            "SELECT book_id, work_group_id FROM book_group_members WHERE book_id IN (?, ?)",
            (book_a, book_b),
        ).fetchall()
    except sqlite3.Error:
        return False, False
    groups: dict[int, set[int]] = {}
    for row in rows:
        groups.setdefault(row["book_id"], set()).add(row["work_group_id"])
    if not groups.get(book_a) or not groups.get(book_b):
        return False, False
    overlap = bool(groups[book_a] & groups[book_b])
    return overlap, not overlap


def compare_books(
    conn: sqlite3.Connection,
    book_a: dict[str, Any],
    book_b: dict[str, Any],
    *,
    text_lookup: TextLookup | None = None,
    high_confidence: float = 0.90,
) -> dict[str, Any]:
    text_lookup = text_lookup or _read_clean_text
    text_a = text_lookup(book_a)
    text_b = text_lookup(book_b)
    title_score = title_similarity(book_a.get("title_norm") or book_a.get("title_raw"), book_b.get("title_norm") or book_b.get("title_raw"))
    author_score = author_similarity(book_a.get("author_norm"), book_b.get("author_norm"))
    chapter_score = jaccard_similarity(_chapter_titles(conn, book_a["id"]), _chapter_titles(conn, book_b["id"]))
    sim_score = simhash_similarity(text_simhash(text_a), text_simhash(text_b)) if text_a or text_b else 0.0
    block_score = jaccard_similarity(chunk_hashes(text_a), chunk_hashes(text_b))
    length_score = length_reasonableness(book_a, book_b)
    score = (
        0.25 * title_score
        + 0.15 * author_score
        + 0.25 * chapter_score
        + 0.20 * sim_score
        + 0.10 * block_score
        + 0.05 * length_score
    )
    risk_flags: list[str] = []
    if author_score == 0.0:
        risk_flags.append("author_conflict")
    if chapter_score < 0.25:
        risk_flags.append("low_chapter_overlap")
    a_len = int(book_a.get("char_count_clean") or 0)
    b_len = int(book_b.get("char_count_clean") or 0)
    ratio = max(a_len, b_len) / max(1, min(a_len, b_len)) if a_len and b_len else 999
    if ratio > 5:
        risk_flags.append("length_gap_large")
    elif ratio >= 1.5 and abs(int(book_a.get("chapter_count") or 0) - int(book_b.get("chapter_count") or 0)) >= 3 and score >= 0.75:
        risk_flags.append("possible_update_version")
    if abs(int(book_a.get("ad_line_count") or 0) - int(book_b.get("ad_line_count") or 0)) >= 20:
        risk_flags.append("possible_ad_heavy_version")
    if max(float(book_a.get("mojibake_rate") or 0), float(book_b.get("mojibake_rate") or 0)) >= 0.03:
        risk_flags.append("possible_mojibake_version")
    if min(float(book_a.get("quality_score") or 0), float(book_b.get("quality_score") or 0)) < 50:
        risk_flags.append("low_quality_candidate")
    if book_a.get("raw_sha256") == book_b.get("raw_sha256") or book_a.get("clean_sha256") == book_b.get("clean_sha256"):
        risk_flags.append("already_exact_duplicate")
    same_group, different_groups = _same_work_groups(conn, book_a["id"], book_b["id"])
    if same_group:
        risk_flags.append("already_same_work_group")
    if different_groups:
        risk_flags.append("already_different_work_group")
    confidence = _confidence_level(score, high_confidence)
    manual_review = confidence != "high_confidence" or bool(risk_flags)
    if "possible_update_version" in risk_flags:
        action = "possible_update_review"
    elif manual_review:
        action = "manual_review"
    else:
        action = "keep_one_review_others"
    primary = sorted([book_a, book_b], key=_rank_key, reverse=True)[0]
    members = []
    for book in sorted([book_a, book_b], key=_rank_key, reverse=True):
        role, reason = _member_role(book, primary, manual_review)
        members.append(
            {
                "book": book,
                "suggested_role": role,
                "reason": reason,
                "similarity_score": round(score, 4),
            }
        )
    return {
        "group_type": "near_duplicate",
        "confidence": round(score, 4),
        "same_work_score": round(score, 4),
        "confidence_level": confidence,
        "recommended_keep_book_id": primary["id"],
        "recommended_action": action,
        "reason_summary": "近似重复候选，需要人工复核" if manual_review else "高置信近似重复候选",
        "risk_flags": sorted(set(risk_flags)),
        "manual_review": manual_review,
        "similarity_breakdown": {
            "title_similarity": round(title_score, 4),
            "author_similarity": round(author_score, 4),
            "chapter_title_overlap": round(chapter_score, 4),
            "simhash_similarity": round(sim_score, 4),
            "block_jaccard": round(block_score, 4),
            "length_reasonableness": round(length_score, 4),
        },
        "members": members,
    }


def _load_books(conn: sqlite3.Connection, area: str, limit: int | None) -> list[dict[str, Any]]:
    if area == "all":
        where, params = "repo_area IN ('library', 'incoming', 'review_duplicates')", []
    else:
        where, params = "repo_area = ?", [area]
    sql = f"SELECT * FROM books WHERE status = 'active' AND {where} ORDER BY id"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def candidate_pairs(
    books: list[dict[str, Any]],
    *,
    min_candidate_title_score: float = 0.85,
    query: str | None = None,
) -> set[tuple[int, int]]:
    by_id = {book["id"]: book for book in books}
    pairs: set[tuple[int, int]] = set()
    title_groups: dict[str, list[int]] = {}
    for book in books:
        title = book.get("title_norm") or normalize_title(book.get("file_name") or "")
        if title:
            title_groups.setdefault(title, []).append(book["id"])
    for ids in title_groups.values():
        for a, b in itertools.combinations(sorted(ids), 2):
            pairs.add((a, b))
    for a, b in itertools.combinations(sorted(by_id), 2):
        left, right = by_id[a], by_id[b]
        if left.get("raw_sha256") and left.get("raw_sha256") == right.get("raw_sha256"):
            continue
        if left.get("clean_sha256") and left.get("clean_sha256") == right.get("clean_sha256"):
            continue
        ts = title_similarity(left.get("title_norm") or left.get("file_name"), right.get("title_norm") or right.get("file_name"))
        file_ts = title_similarity(left.get("file_name"), right.get("file_name"))
        threshold = min_candidate_title_score
        if query and (
            query in (left.get("file_name") or "")
            or query in (left.get("title_raw") or "")
            or query in (left.get("title_norm") or "")
            or query in (right.get("file_name") or "")
            or query in (right.get("title_raw") or "")
            or query in (right.get("title_norm") or "")
        ):
            threshold = min(threshold, 0.70)
        if ts >= threshold or file_ts >= threshold:
            pairs.add((a, b))
        elif left.get("author_norm") and left.get("author_norm") == right.get("author_norm") and ts >= max(0.70, threshold - 0.10):
            pairs.add((a, b))
    return pairs


def find_near_duplicates(
    conn: sqlite3.Connection,
    *,
    area: str = "all",
    min_score: float = 0.82,
    high_confidence: float = 0.90,
    include_low_confidence: bool = False,
    limit: int | None = None,
    text_lookup: TextLookup | None = None,
    min_candidate_title_score: float = 0.85,
) -> list[dict[str, Any]]:
    books = _load_books(conn, area, limit)
    by_id = {book["id"]: book for book in books}
    groups: list[dict[str, Any]] = []
    threshold = 0.65 if include_low_confidence else min_score
    for a, b in sorted(candidate_pairs(books, min_candidate_title_score=min_candidate_title_score)):
        left, right = by_id[a], by_id[b]
        if left.get("raw_sha256") == right.get("raw_sha256") or left.get("clean_sha256") == right.get("clean_sha256"):
            continue
        result = compare_books(conn, left, right, text_lookup=text_lookup, high_confidence=high_confidence)
        if result["same_work_score"] >= threshold and (include_low_confidence or result["same_work_score"] >= min_score):
            result["id"] = f"near-{len(groups) + 1}"
            groups.append(result)
    return groups


def apply_near_duplicates(conn: sqlite3.Connection, groups: list[dict[str, Any]], *, min_score: float = 0.82) -> list[int]:
    inserted: list[int] = []
    for group in groups:
        if float(group.get("same_work_score") or 0) < min_score:
            continue
        conn.execute(
            """
            INSERT INTO duplicate_groups
            (group_type, confidence, recommended_keep_book_id, recommended_action, reason_summary, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "near_duplicate",
                group["same_work_score"],
                group["recommended_keep_book_id"],
                group["recommended_action"],
                group["reason_summary"],
                now_ts(),
                "open",
            ),
        )
        group_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        group["id"] = group_id
        for member in group["members"]:
            conn.execute(
                """
                INSERT INTO duplicate_group_members
                (duplicate_group_id, book_id, similarity_score, quality_score, suggested_role, reason)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    group_id,
                    member["book"]["id"],
                    group["same_work_score"],
                    member["book"].get("quality_score"),
                    member["suggested_role"],
                    member["reason"],
                ),
            )
        inserted.append(group_id)
    if inserted:
        conn.execute(
            "INSERT INTO operations (operation_type, status, reason, created_at, applied_at) VALUES (?, ?, ?, ?, ?)",
            ("apply_near_duplicate", "success", f"duplicate_group_ids={inserted}", now_ts(), now_ts()),
        )
    conn.commit()
    return inserted


def apply_near_to_work_groups(conn: sqlite3.Connection, groups: list[dict[str, Any]]) -> list[int]:
    candidates = []
    for group in groups:
        if group.get("confidence_level") != "high_confidence" or group.get("risk_flags"):
            continue
        book_ids = [member["book"]["id"] for member in group["members"]]
        existing = conn.execute(
            f"SELECT DISTINCT work_group_id FROM book_group_members WHERE book_id IN ({','.join('?' for _ in book_ids)})",
            book_ids,
        ).fetchall()
        if existing:
            continue
        members = []
        for member in group["members"]:
            book = member["book"]
            role = "primary" if book["id"] == group["recommended_keep_book_id"] else "version"
            members.append(
                {
                    "book_id": book["id"],
                    "role": role,
                    "confidence": group["same_work_score"],
                    "source": "near_duplicate",
                    "member_reason": member["reason"],
                }
            )
        primary = next(member["book"] for member in group["members"] if member["book"]["id"] == group["recommended_keep_book_id"])
        candidates.append(
            {
                "canonical_title": primary.get("title_norm") or primary.get("title_raw") or primary.get("file_name"),
                "canonical_author": primary.get("author_norm") or primary.get("author_raw"),
                "recommended_primary_book_id": primary["id"],
                "group_confidence": group["same_work_score"],
                "group_source": "near_duplicate",
                "group_reason": group["reason_summary"],
                "manual_review": False,
                "members": members,
            }
        )
    applied = apply_group_candidates(conn, candidates, min_confidence=0.0) if candidates else []
    if applied:
        conn.execute(
            "INSERT INTO operations (operation_type, status, reason, created_at, applied_at) VALUES (?, ?, ?, ?, ?)",
            ("apply_to_work_group", "success", f"work_group_ids={applied}", now_ts(), now_ts()),
        )
        conn.commit()
    return applied
