from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .fingerprint import normalize_title
from .near_duplicate import _load_books, candidate_pairs, compare_books, title_similarity
from .utils import ensure_dir, file_ts, write_json


def _env() -> Environment:
    template_dir = Path(__file__).resolve().parent.parent / "templates"
    return Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html", "xml"]))


def _matches_query(book: dict[str, Any], query: str | None) -> bool:
    if not query:
        return True
    return any(query in str(book.get(field) or "") for field in ("file_name", "title_raw", "title_norm"))


def _filter_status(result: dict[str, Any], include_exact: bool) -> tuple[str, str]:
    risks = set(result.get("risk_flags") or [])
    score = float(result.get("same_work_score") or 0)
    level = result.get("confidence_level")
    if "already_exact_duplicate" in risks and not include_exact:
        return "skipped_exact_duplicate", "raw_sha256 或 clean_sha256 完全相同，near 默认跳过 exact duplicate。"
    if "already_same_work_group" in risks:
        return "skipped_same_work_group", "两本书已经属于同一 work_group。"
    if "author_conflict" in risks:
        return "rejected_author_conflict", "标题或正文相似但作者冲突，必须人工确认。"
    if level == "high_confidence":
        return "accepted_high_confidence", "达到高置信阈值。"
    if level == "probable_duplicate":
        return "accepted_probable", "达到近似重复默认阈值，但需要人工复核。"
    if level == "suspicious":
        return "accepted_suspicious", "低置信可疑候选，仅用于诊断或 include-low-confidence。"
    return "rejected_below_threshold", f"same_work_score={score:.4f} 低于近似重复阈值。"


def _pair_row(pair_id: int, a: dict[str, Any], b: dict[str, Any], result: dict[str, Any], include_exact: bool) -> dict[str, Any]:
    status, reason = _filter_status(result, include_exact)
    breakdown = result.get("similarity_breakdown") or {}
    return {
        "pair_id": pair_id,
        "book_a_id": a["id"],
        "book_b_id": b["id"],
        "file_a": a.get("file_name"),
        "file_b": b.get("file_name"),
        "title_a": a.get("title_raw"),
        "title_b": b.get("title_raw"),
        "title_norm_a": a.get("title_norm"),
        "title_norm_b": b.get("title_norm"),
        "author_a": a.get("author_norm"),
        "author_b": b.get("author_norm"),
        "char_count_a": a.get("char_count_clean"),
        "char_count_b": b.get("char_count_clean"),
        "chapter_count_a": a.get("chapter_count"),
        "chapter_count_b": b.get("chapter_count"),
        "quality_score_a": a.get("quality_score"),
        "quality_score_b": b.get("quality_score"),
        "title_similarity": breakdown.get("title_similarity", 0),
        "author_similarity": breakdown.get("author_similarity", 0),
        "chapter_title_overlap": breakdown.get("chapter_title_overlap", 0),
        "simhash_similarity": breakdown.get("simhash_similarity", 0),
        "block_jaccard": breakdown.get("block_jaccard", 0),
        "length_reasonableness": breakdown.get("length_reasonableness", 0),
        "same_work_score": result.get("same_work_score", 0),
        "confidence_level": result.get("confidence_level"),
        "risk_flags": result.get("risk_flags") or [],
        "filter_status": status,
        "filter_reason": reason,
    }


def _title_samples(books: list[dict[str, Any]], query: str | None, limit: int = 80) -> list[dict[str, Any]]:
    selected = [book for book in books if _matches_query(book, query)] if query else books
    rows = []
    for book in selected[:limit]:
        rows.append(
            {
                "book_id": book["id"],
                "file_name": book.get("file_name"),
                "title_raw": book.get("title_raw"),
                "title_norm": book.get("title_norm"),
                "author_norm": book.get("author_norm"),
                "file_name_norm": normalize_title(book.get("file_name")),
            }
        )
    return rows


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 近似重复诊断",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 仓库路径：`{payload['repo']}`",
        f"- 候选对数量：{len(payload['pairs'])}",
        "",
        "## 标题规范化样例",
        "",
        "| book_id | file_name | title_raw | title_norm | author_norm | file_name_norm |",
        "|---:|---|---|---|---|---|",
    ]
    for row in payload["title_samples"]:
        lines.append(
            f"| {row['book_id']} | `{row['file_name']}` | {row['title_raw']} | {row['title_norm']} | {row['author_norm']} | {row['file_name_norm']} |"
        )
    lines.extend(
        [
            "",
            "## 候选对诊断",
            "",
            "| pair | A | B | title | chapter | simhash | block | score | status | reason |",
            "|---:|---|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in payload["pairs"]:
        lines.append(
            f"| {row['pair_id']} | `{row['file_a']}` | `{row['file_b']}` | {row['title_similarity']:.4f} | {row['chapter_title_overlap']:.4f} | {row['simhash_similarity']:.4f} | {row['block_jaccard']:.4f} | {row['same_work_score']:.4f} | {row['filter_status']} | {row['filter_reason']} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def diagnose_near(
    conn,
    repo: Path,
    *,
    area: str = "all",
    query: str | None = None,
    min_candidate_title_score: float = 0.70,
    limit: int = 200,
    include_exact: bool = False,
    text_lookup=None,
) -> dict[str, Any]:
    books = _load_books(conn, area, None)
    if query:
        query_books = [book for book in books if _matches_query(book, query)]
        query_ids = {book["id"] for book in query_books}
        expanded = []
        for book in books:
            if book["id"] in query_ids:
                expanded.append(book)
                continue
            if any(title_similarity(book.get("title_norm") or book.get("file_name"), q.get("title_norm") or q.get("file_name")) >= min_candidate_title_score for q in query_books):
                expanded.append(book)
        books = expanded
    by_id = {book["id"]: book for book in books}
    pairs = candidate_pairs(books, min_candidate_title_score=min_candidate_title_score, query=query)
    if query:
        pairs = {pair for pair in pairs if _matches_query(by_id[pair[0]], query) or _matches_query(by_id[pair[1]], query)}
    rows = []
    for pair_id, (a_id, b_id) in enumerate(sorted(pairs), 1):
        if len(rows) >= limit:
            break
        a, b = by_id[a_id], by_id[b_id]
        result = compare_books(conn, a, b, text_lookup=text_lookup)
        row = _pair_row(pair_id, a, b, result, include_exact)
        if row["filter_status"] == "skipped_exact_duplicate" and include_exact:
            row["filter_status"] = "accepted_high_confidence"
            row["filter_reason"] = "exact duplicate pair included for diagnostic visibility."
        rows.append(row)

    ts = file_ts()
    out_dir = repo / "reports" / "diagnostic"
    ensure_dir(out_dir)
    payload = {
        "generated_at": ts,
        "repo": str(repo),
        "area": area,
        "query": query,
        "min_candidate_title_score": min_candidate_title_score,
        "include_exact": include_exact,
        "title_samples": _title_samples(books, query),
        "pairs": rows,
    }
    json_path = out_dir / f"near_diagnostic_{ts}.json"
    html_path = out_dir / f"near_diagnostic_{ts}.html"
    md_path = out_dir / f"near_diagnostic_{ts}.md"
    write_json(json_path, payload)
    html_path.write_text(_env().get_template("near_diagnostic.html.j2").render(**payload), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    return {"json_path": json_path, "html_path": html_path, "md_path": md_path, "payload": payload}
