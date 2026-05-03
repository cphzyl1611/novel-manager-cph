from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .near_duplicate import (
    author_similarity,
    chunk_hashes,
    jaccard_similarity,
    length_reasonableness,
    simhash_similarity,
    text_simhash,
    title_similarity,
)
from .scanner import detect_and_decode
from .text_cleaner import clean_text
from .utils import ensure_dir, file_ts, now_ts, write_json

TextLookup = Callable[[dict[str, Any]], str]


def _default_text_lookup(max_chars: int = 200_000) -> TextLookup:
    cache: dict[str, str] = {}

    def lookup(book: dict[str, Any]) -> str:
        path = str(book.get("current_path") or "")
        if not path:
            return ""
        if path in cache:
            return cache[path]
        p = Path(path)
        if not p.exists():
            cache[path] = ""
            return ""
        raw = p.read_bytes()
        text, _, _, _ = detect_and_decode(raw)
        cleaned, _ = clean_text(text)
        cache[path] = cleaned[:max_chars]
        return cache[path]

    return lookup


def _env() -> Environment:
    template_dir = Path(__file__).resolve().parent.parent / "templates"
    return Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "xml"]))


def migrate_update_candidates_schema(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(update_candidates)").fetchall()}
    additions = {
        "same_work_score": "REAL",
        "coverage_score": "REAL",
        "new_content_score": "REAL",
        "quality_delta": "REAL",
        "old_chapter_count": "INTEGER",
        "new_chapter_count": "INTEGER",
        "old_char_count": "INTEGER",
        "new_char_count": "INTEGER",
        "new_chapters_count": "INTEGER",
        "matched_old_chapter_rate": "REAL",
        "recommendation": "TEXT",
        "reason_summary": "TEXT",
    }
    for name, ddl in additions.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE update_candidates ADD COLUMN {name} {ddl}")
    conn.commit()


def _chapters(conn: sqlite3.Connection, book_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT chapter_index, chapter_no, title_raw, title_norm FROM chapters WHERE book_id = ? ORDER BY chapter_index",
        (book_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _chapter_set(chapters: list[dict[str, Any]]) -> set[str]:
    return {ch["title_norm"] for ch in chapters if ch.get("title_norm")}


def compute_same_work_score(
    conn: sqlite3.Connection,
    old_book: dict[str, Any],
    new_book: dict[str, Any],
    old_chapters: list[dict[str, Any]],
    new_chapters: list[dict[str, Any]],
    *,
    text_lookup: TextLookup | None = None,
) -> dict[str, Any]:
    text_lookup = text_lookup or _default_text_lookup()
    old_text = text_lookup(old_book)
    new_text = text_lookup(new_book)
    title_score = title_similarity(old_book.get("title_norm") or old_book.get("file_name"), new_book.get("title_norm") or new_book.get("file_name"))
    author_score = author_similarity(old_book.get("author_norm"), new_book.get("author_norm"))
    chapter_score = jaccard_similarity(_chapter_set(old_chapters), _chapter_set(new_chapters))
    simhash_score = simhash_similarity(text_simhash(old_text), text_simhash(new_text)) if old_text or new_text else 0.0
    block_score = jaccard_similarity(chunk_hashes(old_text), chunk_hashes(new_text))
    length_score = length_reasonableness(old_book, new_book)
    score = (
        0.25 * title_score
        + 0.15 * author_score
        + 0.25 * chapter_score
        + 0.20 * simhash_score
        + 0.10 * block_score
        + 0.05 * length_score
    )
    return {
        "same_work_score": round(score, 4),
        "title_similarity": round(title_score, 4),
        "author_similarity": round(author_score, 4),
        "chapter_title_overlap": round(chapter_score, 4),
        "simhash_similarity": round(simhash_score, 4),
        "block_jaccard": round(block_score, 4),
        "length_reasonableness": round(length_score, 4),
    }


def compute_coverage_score(old_chapters: list[dict[str, Any]], new_chapters: list[dict[str, Any]]) -> dict[str, Any]:
    old_titles = [ch["title_norm"] for ch in old_chapters if ch.get("title_norm")]
    new_titles = [ch["title_norm"] for ch in new_chapters if ch.get("title_norm")]
    if not old_titles or not new_titles:
        return {"coverage_score": 0.0, "matched_old_chapter_rate": 0.0, "missing_old_chapters_sample": old_titles[:20]}
    new_set = set(new_titles)
    matched = [title for title in old_titles if title in new_set]
    missing = [title for title in old_titles if title not in new_set]
    return {
        "coverage_score": round(len(matched) / len(old_titles), 4),
        "matched_old_chapter_rate": round(len(matched) / len(old_titles), 4),
        "missing_old_chapters_sample": missing[:20],
    }


def compute_new_content_score(old_book: dict[str, Any], new_book: dict[str, Any], old_chapters: list[dict[str, Any]], new_chapters: list[dict[str, Any]]) -> dict[str, Any]:
    old_count = int(old_book.get("chapter_count") or len(old_chapters) or 0)
    new_count = int(new_book.get("chapter_count") or len(new_chapters) or 0)
    old_chars = int(old_book.get("char_count_clean") or 0)
    new_chars = int(new_book.get("char_count_clean") or 0)
    chapter_delta = new_count - old_count
    char_delta = new_chars - old_chars
    chapter_gain = max(0.0, chapter_delta / max(1, old_count))
    char_gain = max(0.0, char_delta / max(1, old_chars))
    score = min(1.0, chapter_gain * 1.5 + char_gain)
    old_titles = _chapter_set(old_chapters)
    new_only = [ch.get("title_norm") or ch.get("title_raw") for ch in new_chapters if ch.get("title_norm") and ch.get("title_norm") not in old_titles]
    return {
        "new_content_score": round(score, 4),
        "chapter_count_delta": chapter_delta,
        "char_count_delta": char_delta,
        "new_chapters_count": max(0, chapter_delta),
        "new_chapters_sample": new_only[:20],
    }


def compute_quality_delta(old_book: dict[str, Any], new_book: dict[str, Any]) -> dict[str, Any]:
    return {
        "quality_delta": round(float(new_book.get("quality_score") or 0) - float(old_book.get("quality_score") or 0), 4),
        "ad_line_delta": int(new_book.get("ad_line_count") or 0) - int(old_book.get("ad_line_count") or 0),
        "mojibake_delta": round(float(new_book.get("mojibake_rate") or 0) - float(old_book.get("mojibake_rate") or 0), 6),
        "duplicate_chapter_delta": int(new_book.get("duplicate_chapter_count") or 0) - int(old_book.get("duplicate_chapter_count") or 0),
        "missing_chapter_delta": int(new_book.get("missing_chapter_count") or 0) - int(old_book.get("missing_chapter_count") or 0),
        "chapter_order_error_delta": int(new_book.get("chapter_order_error_count") or 0) - int(old_book.get("chapter_order_error_count") or 0),
    }


def classify_update_candidate(metrics: dict[str, Any], *, quality_tolerance: float = 5) -> tuple[str, list[str]]:
    risks: list[str] = []
    if metrics["author_similarity"] == 0.0:
        risks.append("author_conflict")
    if metrics["same_work_score"] < 0.75:
        risks.append("low_same_work_score")
    if metrics["coverage_score"] < 0.80:
        risks.append("low_coverage")
    if metrics["new_content_score"] <= 0:
        risks.append("no_new_content")
    if metrics["quality_delta"] < -quality_tolerance:
        risks.append("quality_drop")
    if metrics["ad_line_delta"] > 10:
        risks.append("ad_line_increase")
    if metrics["mojibake_delta"] > 0.01:
        risks.append("mojibake_increase")
    if metrics["duplicate_chapter_delta"] > 0:
        risks.append("duplicate_chapter_increase")
    if metrics["missing_chapter_delta"] > 0:
        risks.append("missing_chapter_increase")
    if metrics["chapter_order_error_delta"] > 0:
        risks.append("chapter_order_worse")
    if metrics["ad_line_delta"] > 50:
        risks.append("possible_ad_inflation")
    if metrics["new_char_count"] < metrics["old_char_count"] * 0.7:
        risks.append("possible_truncated_new_version")
    if metrics["new_content_score"] > 0 and metrics["quality_delta"] >= -quality_tolerance:
        risks.append("new_version_maybe_better")

    severe = {"author_conflict", "low_same_work_score", "low_coverage", "no_new_content", "quality_drop", "mojibake_increase", "ad_line_increase", "possible_truncated_new_version"}
    if metrics["same_work_score"] >= 0.85 and metrics["coverage_score"] >= 0.90 and metrics["new_content_score"] > 0 and not (set(risks) & severe):
        return "replace_recommended", risks
    if set(risks) & {"author_conflict", "low_same_work_score", "low_coverage", "no_new_content", "quality_drop", "mojibake_increase", "ad_line_increase", "possible_truncated_new_version"}:
        return "reject", risks
    if risks:
        risks.append("manual_review_needed")
    return "manual_review", risks


def generate_update_reason(candidate: dict[str, Any]) -> str:
    rec = candidate["recommendation"]
    if rec == "replace_recommended":
        return "新版覆盖旧版章节，存在新增内容，质量未明显下降；仅建议人工确认后处理。"
    if rec == "reject":
        return "候选存在严重风险，不建议作为更新版本。"
    return "候选可能是更新版本，但存在风险或证据不足，需要人工复核。"


def compare_update_pair(
    conn: sqlite3.Connection,
    old_book: dict[str, Any],
    new_book: dict[str, Any],
    old_chapters: list[dict[str, Any]] | None = None,
    new_chapters: list[dict[str, Any]] | None = None,
    *,
    text_lookup: TextLookup | None = None,
    quality_tolerance: float = 5,
) -> dict[str, Any]:
    old_chapters = old_chapters if old_chapters is not None else _chapters(conn, old_book["id"])
    new_chapters = new_chapters if new_chapters is not None else _chapters(conn, new_book["id"])
    same = compute_same_work_score(conn, old_book, new_book, old_chapters, new_chapters, text_lookup=text_lookup)
    coverage = compute_coverage_score(old_chapters, new_chapters)
    content = compute_new_content_score(old_book, new_book, old_chapters, new_chapters)
    quality = compute_quality_delta(old_book, new_book)
    metrics = {
        **same,
        **coverage,
        **content,
        **quality,
        "old_chapter_count": int(old_book.get("chapter_count") or 0),
        "new_chapter_count": int(new_book.get("chapter_count") or 0),
        "old_char_count": int(old_book.get("char_count_clean") or 0),
        "new_char_count": int(new_book.get("char_count_clean") or 0),
    }
    recommendation, risks = classify_update_candidate(metrics, quality_tolerance=quality_tolerance)
    candidate = {
        "old_book_id": old_book["id"],
        "new_book_id": new_book["id"],
        "old_file": old_book.get("file_name"),
        "new_file": new_book.get("file_name"),
        "old_path": old_book.get("current_path"),
        "new_path": new_book.get("current_path"),
        "old_title": old_book.get("title_norm") or old_book.get("title_raw"),
        "new_title": new_book.get("title_norm") or new_book.get("title_raw"),
        "old_author": old_book.get("author_norm") or old_book.get("author_raw"),
        "new_author": new_book.get("author_norm") or new_book.get("author_raw"),
        **metrics,
        "recommendation": recommendation,
        "risk_flags": sorted(set(risks)),
    }
    candidate["reason_summary"] = generate_update_reason(candidate)
    candidate.update(
        {
            "old_quality_score": old_book.get("quality_score"),
            "new_quality_score": new_book.get("quality_score"),
            "old_ad_line_count": old_book.get("ad_line_count"),
            "new_ad_line_count": new_book.get("ad_line_count"),
            "old_mojibake_rate": old_book.get("mojibake_rate"),
            "new_mojibake_rate": new_book.get("mojibake_rate"),
            "old_missing_chapter_count": old_book.get("missing_chapter_count"),
            "new_missing_chapter_count": new_book.get("missing_chapter_count"),
            "old_duplicate_chapter_count": old_book.get("duplicate_chapter_count"),
            "new_duplicate_chapter_count": new_book.get("duplicate_chapter_count"),
        }
    )
    return candidate


def _load_books(conn: sqlite3.Connection, area: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM books WHERE status = 'active' AND repo_area = ? ORDER BY id", (area,)).fetchall()
    return [dict(row) for row in rows]


def _matches_query(book: dict[str, Any], query: str | None) -> bool:
    if not query:
        return True
    return any(query in str(book.get(field) or "") for field in ("file_name", "title_raw", "title_norm"))


def _candidate_pairs(library_books: list[dict[str, Any]], incoming_books: list[dict[str, Any]], query: str | None) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    pairs = []
    for new in incoming_books:
        if query and not _matches_query(new, query):
            continue
        for old in library_books:
            if query and not (_matches_query(old, query) or _matches_query(new, query)):
                continue
            ts = title_similarity(old.get("title_norm") or old.get("file_name"), new.get("title_norm") or new.get("file_name"))
            threshold = 0.70 if query else 0.85
            if (old.get("title_norm") and old.get("title_norm") == new.get("title_norm")) or ts >= threshold:
                pairs.append((old, new))
            elif old.get("author_norm") and old.get("author_norm") == new.get("author_norm") and ts >= max(0.70, threshold - 0.10):
                pairs.append((old, new))
    return pairs


def find_update_candidates(
    conn: sqlite3.Connection,
    *,
    min_same_work_score: float = 0.75,
    min_coverage: float = 0.80,
    quality_tolerance: float = 5,
    include_rejected: bool = False,
    query: str | None = None,
    limit: int = 100,
    dry_run: bool = False,
    text_lookup: TextLookup | None = None,
) -> dict[str, Any]:
    library_books = _load_books(conn, "library")
    incoming_books = _load_books(conn, "incoming")
    pairs = _candidate_pairs(library_books, incoming_books, query)
    if dry_run:
        return {"incoming_count": len(incoming_books), "library_count": len(library_books), "pairs_to_check": len(pairs), "candidates": []}
    candidates = []
    for old, new in pairs:
        if len(candidates) >= limit:
            break
        candidate = compare_update_pair(conn, old, new, text_lookup=text_lookup, quality_tolerance=quality_tolerance)
        if candidate["same_work_score"] < min_same_work_score:
            candidate["risk_flags"] = sorted(set(candidate["risk_flags"] + ["low_same_work_score"]))
            candidate["recommendation"] = "reject"
            candidate["reason_summary"] = generate_update_reason(candidate)
        if candidate["coverage_score"] < min_coverage:
            candidate["risk_flags"] = sorted(set(candidate["risk_flags"] + ["low_coverage"]))
            candidate["recommendation"] = "reject"
            candidate["reason_summary"] = generate_update_reason(candidate)
        if include_rejected or candidate["recommendation"] != "reject":
            candidate["candidate_id"] = len(candidates) + 1
            candidates.append(candidate)
    return {"incoming_count": len(incoming_books), "library_count": len(library_books), "pairs_to_check": len(pairs), "candidates": candidates}


def save_update_candidates(conn: sqlite3.Connection, candidates: list[dict[str, Any]]) -> int:
    migrate_update_candidates_schema(conn)
    count = 0
    for c in candidates:
        conn.execute(
            """
            INSERT INTO update_candidates
            (old_book_id, new_book_id, confidence, reason, status, created_at,
             same_work_score, coverage_score, new_content_score, quality_delta,
             old_chapter_count, new_chapter_count, old_char_count, new_char_count,
             new_chapters_count, matched_old_chapter_rate, recommendation, reason_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                c["old_book_id"],
                c["new_book_id"],
                c["same_work_score"],
                c["reason_summary"],
                c["recommendation"],
                now_ts(),
                c["same_work_score"],
                c["coverage_score"],
                c["new_content_score"],
                c["quality_delta"],
                c["old_chapter_count"],
                c["new_chapter_count"],
                c["old_char_count"],
                c["new_char_count"],
                c["new_chapters_count"],
                c["matched_old_chapter_rate"],
                c["recommendation"],
                c["reason_summary"],
            ),
        )
        count += 1
    conn.commit()
    return count


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 更新检测报告",
        "",
        "本报告不执行替换。",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- incoming 文件数：{payload['incoming_count']}",
        f"- library 文件数：{payload['library_count']}",
        f"- 候选数量：{len(payload['candidates'])}",
        "",
        "| candidate | old | new | same | coverage | new_content | quality_delta | recommendation | risks |",
        "|---:|---|---|---:|---:|---:|---:|---|---|",
    ]
    for c in payload["candidates"]:
        lines.append(
            f"| {c['candidate_id']} | `{c['old_file']}` | `{c['new_file']}` | {c['same_work_score']:.4f} | {c['coverage_score']:.4f} | {c['new_content_score']:.4f} | {c['quality_delta']:.2f} | {c['recommendation']} | {';'.join(c['risk_flags'])} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def generate_update_report(repo: Path, result: dict[str, Any], saved_count: int = 0) -> tuple[Path, Path, Path]:
    ts = file_ts()
    out_dir = repo / "reports" / "update"
    ensure_dir(out_dir)
    payload = {"generated_at": ts, "saved_count": saved_count, **result}
    json_path = out_dir / f"update_report_{ts}.json"
    html_path = out_dir / f"update_report_{ts}.html"
    md_path = out_dir / f"update_report_{ts}.md"
    write_json(json_path, payload)
    html_path.write_text(_env().get_template("update_report.html.j2").render(**payload), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    return html_path, json_path, md_path
