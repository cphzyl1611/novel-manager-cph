from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from ...db import connect as db_connect
from ...scanner import scan_file
from ...update_detector import compare_update_pair, _chapters
from ...near_duplicate import title_similarity, author_similarity
from ...utils import ensure_dir, now_ts

MAX_FILE_SIZE = 50 * 1024 * 1024
ALLOWED_EXT = {".txt"}


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "", name).strip().strip(".")
    if not cleaned:
        cleaned = f"upload_{_ts_now()}"
    if not cleaned.lower().endswith(".txt"):
        cleaned += ".txt"
    return cleaned


def is_allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXT


def safe_incoming_path(repo_path: Path, filename: str) -> Path:
    safe_name = sanitize_filename(filename)
    incoming = repo_path / "incoming"
    ensure_dir(incoming)
    target = (incoming / safe_name).resolve()
    try:
        target.relative_to(incoming.resolve())
    except ValueError:
        raise ValueError("路径穿越被拒绝")
    return target


def _ts_now() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _unique_target(target: Path) -> Path:
    if not target.exists():
        return target
    stem = target.stem
    ts = _ts_now()
    for n in range(200):
        suffix = f"__upload_{ts}" + (f"_{n}" if n else "")
        candidate = target.with_stem(f"{stem}{suffix}")
        if not candidate.exists():
            return candidate
    raise OSError("无法生成唯一文件名")


def save_upload(repo_path: str, filename: str, content: bytes) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    if not is_allowed_file(filename):
        return {"status": "skipped", "original_name": filename, "reason": "只支持 TXT 文件"}
    if len(content) > MAX_FILE_SIZE:
        return {"status": "skipped", "original_name": filename, "reason": f"文件超过 {MAX_FILE_SIZE // 1024 // 1024}MB 限制"}
    try:
        target = safe_incoming_path(root, filename)
    except ValueError:
        return {"status": "skipped", "original_name": filename, "reason": "文件名不安全"}
    final_path = _unique_target(target)
    final_path.write_bytes(content)
    _write_log(root, f"upload_to_incoming web {final_path} {len(content)} success")
    return {"status": "success", "original_name": filename, "saved_name": final_path.name, "path": str(final_path), "size": len(content)}


def scan_incoming(repo_path: str) -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    incoming = root / "incoming"
    if not incoming.exists():
        return {"found": 0, "scanned": 0, "skipped": 0, "errors": []}

    txt_files = sorted([p for p in incoming.glob("*.txt") if p.is_file()])
    found = len(txt_files)
    scanned = 0
    skipped = 0
    error_list: list[dict] = []

    try:
        conn = db_connect(root)
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        return {"found": found, "scanned": 0, "skipped": 0, "errors": [{"error": "无法连接数据库"}], "files": [f.name for f in txt_files]}

    for fp in txt_files:
        try:
            result = scan_file(conn, root, "incoming", fp, dry_run=False)
            if result["status"] == "scanned":
                scanned += 1
            else:
                skipped += 1
                error_list.append({"file": fp.name, "error": result.get("error", "unknown")})
        except Exception as exc:
            skipped += 1
            error_list.append({"file": fp.name, "error": str(exc)})

    conn.close()
    _write_log(root, f"scan_incoming found={found} scanned={scanned} skipped={skipped}")
    return {"found": found, "scanned": scanned, "skipped": skipped, "errors": error_list}


def analyze_incoming(repo_path: str) -> dict[str, Any]:
    """Analyze incoming books and classify them."""
    root = Path(repo_path).expanduser().resolve()
    try:
        conn = db_connect(root)
        conn.row_factory = sqlite3.Row
        incoming_books = conn.execute("SELECT * FROM books WHERE repo_area = 'incoming'").fetchall()
        if not incoming_books:
            conn.close()
            return _empty_analysis()
        library_books = conn.execute("SELECT * FROM books WHERE repo_area = 'library'").fetchall()
    except Exception:
        return _empty_analysis()

    lib_by_raw = {r["raw_sha256"]: dict(r) for r in library_books if r["raw_sha256"]}
    lib_by_clean = {r["clean_sha256"]: dict(r) for r in library_books if r["clean_sha256"]}
    lib_list = [dict(r) for r in library_books]

    items: list[dict] = []
    summary = {"incoming_count": len(incoming_books), "new_book": 0, "exact_duplicate": 0, "update_candidate": 0, "near_duplicate": 0, "manual_review": 0, "reject": 0}

    for ib in incoming_books:
        ib_dict = dict(ib)
        ib_id = ib["id"]
        item = {
            "incoming_book_id": ib_id,
            "incoming_title": ib["title_norm"] or ib["title_raw"] or ib["file_name"],
            "incoming_file": ib["file_name"] or "",
            "classification": "new_book",
            "classification_label": "新书",
            "matched_book_id": None,
            "matched_title": None,
            "confidence": 1.0,
            "same_work_score": None,
            "old_coverage": None,
            "new_content_ratio": None,
            "chapter_growth": None,
            "quality_delta": None,
            "recommendation": "import_candidate",
            "reason": "未匹配到已有书籍，建议导入书库。",
            "risks": [],
            "top_matches": [],
        }

        raw_hash = ib["raw_sha256"]
        clean_hash = ib["clean_sha256"]
        matched = None

        if raw_hash and raw_hash in lib_by_raw:
            matched = lib_by_raw[raw_hash]
            item["classification"] = "exact_duplicate"
            item["classification_label"] = "简单重复"
            item["recommendation"] = "duplicate_review"
            item["reason"] = "内容完全相同的文件已存在，建议保留质量更高版本，另一份移入重复复核区。"
            item["confidence"] = 1.0
            item["matched_book_id"] = matched["id"]
            item["matched_title"] = matched.get("title_norm") or matched.get("file_name")
        elif clean_hash and clean_hash in lib_by_clean:
            matched = lib_by_clean[clean_hash]
            item["classification"] = "exact_duplicate"
            item["classification_label"] = "简单重复（清洗后）"
            item["recommendation"] = "duplicate_review"
            item["reason"] = "去除广告后内容相同的文件已存在。"
            item["confidence"] = 0.99
            item["matched_book_id"] = matched["id"]
            item["matched_title"] = matched.get("title_norm") or matched.get("file_name")

        if matched is None:
            matched = _find_in_update_report(conn, ib_id)

        if matched:
            item["matched_book_id"] = matched.get("id") or matched.get("old_book_id")
            item["matched_title"] = matched.get("title_norm") or matched.get("old_title")
            if "same_work_score" in matched:
                item["same_work_score"] = matched.get("same_work_score")
                item["old_coverage"] = matched.get("coverage_score")
                item["new_content_ratio"] = matched.get("new_content_score")
                item["chapter_growth"] = (matched.get("new_chapter_count") or 0) - (matched.get("old_chapter_count") or 0)
                item["quality_delta"] = matched.get("quality_delta")
                rec = matched.get("recommendation", "")
                if rec == "replace_recommended":
                    item["classification"] = "update_candidate"
                    item["classification_label"] = "可能是新版"
                    item["recommendation"] = "manual_review"
                    item["reason"] = "新版覆盖旧版大部分内容并有新增章节，建议人工确认后替换。"
                elif rec == "reject":
                    item["classification"] = "risky"
                    item["classification_label"] = "风险"
                    item["recommendation"] = "reject"
                    item["reason"] = matched.get("reason_summary", "候选存在严重风险。")
                else:
                    item["classification"] = "manual_review"
                    item["classification_label"] = "需人工确认"
                    item["reason"] = matched.get("reason_summary", "需人工复核。")
                item["risks"] = matched.get("risk_flags", [])

        if matched is None:
            near_match = _find_in_duplicate_groups(conn, ib_id)
            if near_match:
                item.update(near_match)
                matched = {"id": near_match.get("matched_book_id")}

        if matched is None:
            update_match = _find_update_candidate_live(conn, ib_dict, lib_list)
            if update_match:
                item.update(update_match)
                matched = {"id": update_match.get("matched_book_id")}

        top_matches = _find_top_similar_library(conn, ib_dict, lib_list, top_n=3)
        item["top_matches"] = top_matches

        if matched is None and top_matches:
            best = top_matches[0]
            if best["same_work_score"] >= 0.80:
                item["classification"] = "manual_review"
                item["classification_label"] = "需人工确认"
                item["matched_book_id"] = best["book_id"]
                item["matched_title"] = best["title"]
                item["same_work_score"] = best["same_work_score"]
                item["old_coverage"] = best.get("old_coverage")
                item["new_content_ratio"] = best.get("new_content_ratio")
                item["chapter_growth"] = best.get("chapter_growth")
                item["char_count_delta"] = best.get("char_count_delta")
                item["quality_delta"] = best.get("quality_delta")
                item["recommendation"] = "manual_review"
                item["reason"] = f"存在高度相似旧书《{best['title']}》（同书分 {best['same_work_score']:.2f}），但新增内容证据不足，建议人工确认。"
                item["update_type"] = "similar_only"
                matched = {"id": best["book_id"]}
            else:
                item["reason"] = f"存在相似旧书《{best['title']}》（同书分 {best['same_work_score']:.2f}），但未达到新版判断阈值。"

        summary[item["classification"]] = summary.get(item["classification"], 0) + 1
        items.append(item)

    conn.close()

    report = {"summary": summary, "items": items, "generated_at": now_ts(), "repo_path": str(root), "algorithm_version": "2.0"}
    _save_analysis_report(root, report)
    return report


def _find_update_candidate_live(conn, incoming_book: dict, library_books: list[dict]) -> dict | None:
    """Live detection of update candidates by comparing incoming with library books."""
    incoming_title = incoming_book.get("title_norm") or incoming_book.get("title_raw") or incoming_book.get("file_name")
    incoming_author = incoming_book.get("author_norm") or incoming_book.get("author_raw")
    incoming_chapters = int(incoming_book.get("chapter_count") or 0)
    incoming_chars = int(incoming_book.get("char_count_clean") or 0)

    candidates = []
    for lib_book in library_books:
        lib_title = lib_book.get("title_norm") or lib_book.get("title_raw") or lib_book.get("file_name")
        lib_author = lib_book.get("author_norm") or lib_book.get("author_raw")

        title_score = title_similarity(incoming_title, lib_title)
        if title_score < 0.70:
            continue

        author_score = author_similarity(incoming_author, lib_author)
        lib_chapters = int(lib_book.get("chapter_count") or 0)
        lib_chars = int(lib_book.get("char_count_clean") or 0)

        chapter_growth = incoming_chapters - lib_chapters
        char_count_delta = incoming_chars - lib_chars

        if title_score >= 0.85 and (author_score >= 0.8 or author_score <= 0.5):
            try:
                incoming_ch_list = _chapters(conn, incoming_book["id"])
                lib_ch_list = _chapters(conn, lib_book["id"])
                comparison = compare_update_pair(conn, lib_book, incoming_book, lib_ch_list, incoming_ch_list)

                same_work = comparison.get("same_work_score", 0)
                coverage = comparison.get("coverage_score", 0)
                new_content = comparison.get("new_content_score", 0)
                quality_delta = comparison.get("quality_delta", 0)

                candidates.append({
                    "book_id": lib_book["id"],
                    "title": lib_title,
                    "same_work_score": same_work,
                    "coverage_score": coverage,
                    "new_content_score": new_content,
                    "quality_delta": quality_delta,
                    "chapter_growth": chapter_growth,
                    "char_count_delta": char_count_delta,
                    "risks": comparison.get("risk_flags", []),
                    "recommendation": comparison.get("recommendation"),
                    "reason_summary": comparison.get("reason_summary"),
                    "comparison": comparison,
                    "author_conflict": author_score == 0.0,
                    "title_score": title_score,
                })
            except Exception:
                pass

    if not candidates:
        return None

    candidates.sort(key=lambda x: x["same_work_score"], reverse=True)
    best = candidates[0]

    same_work = best["same_work_score"]
    coverage = best["coverage_score"]
    new_content = best["new_content_score"]
    quality_delta = best["quality_delta"]
    chapter_growth = best["chapter_growth"]
    char_count_delta = best["char_count_delta"]
    title_score = best.get("title_score", 0)
    risks = list(best["risks"])

    if best.get("author_conflict"):
        risks.append("author_conflict")

    severe_risks = {"author_conflict", "low_same_work_score", "low_coverage", "possible_truncated_new_version"}

    is_minor_update = (
        (same_work >= 0.88 or title_score >= 0.92)
        and coverage >= 0.90
        and (chapter_growth >= 1 or new_content >= 0.005 or char_count_delta >= 500)
        and quality_delta >= -15
    )

    is_major_update = (
        same_work >= 0.85
        and coverage >= 0.85
        and (new_content >= 0.03 or chapter_growth >= 2)
        and quality_delta >= -10
        and not (set(risks) & severe_risks)
    )

    if is_major_update:
        return {
            "classification": "update_candidate",
            "classification_label": "可能是新版",
            "matched_book_id": best["book_id"],
            "matched_title": best["title"],
            "same_work_score": round(same_work, 4),
            "old_coverage": round(coverage, 4),
            "new_content_ratio": round(new_content, 4),
            "chapter_growth": chapter_growth,
            "char_count_delta": char_count_delta,
            "quality_delta": round(quality_delta, 2),
            "recommendation": "manual_review",
            "reason": f"新下载版本与书架中《{best['title']}》高度相似（同书分 {same_work:.2f}），且新增了约 {new_content*100:.1f}% 内容，可能是新版。建议查看对比后再替换。",
            "risks": risks,
            "confidence": round(same_work, 2),
            "update_type": "major_update",
        }

    if is_minor_update:
        return {
            "classification": "update_candidate",
            "classification_label": "可能是小幅更新",
            "matched_book_id": best["book_id"],
            "matched_title": best["title"],
            "same_work_score": round(same_work, 4),
            "old_coverage": round(coverage, 4),
            "new_content_ratio": round(new_content, 4),
            "chapter_growth": chapter_growth,
            "char_count_delta": char_count_delta,
            "quality_delta": round(quality_delta, 2),
            "recommendation": "manual_review",
            "reason": f"新下载版本与书架旧版高度相似（同书分 {same_work:.2f}），并包含少量新增内容（约 {char_count_delta} 字），疑似小幅更新版本，建议人工确认后再替换。",
            "risks": risks,
            "confidence": round(same_work, 2),
            "update_type": "minor_update",
        }

    if same_work >= 0.80:
        return {
            "classification": "manual_review",
            "classification_label": "需人工确认",
            "matched_book_id": best["book_id"],
            "matched_title": best["title"],
            "same_work_score": round(same_work, 4),
            "old_coverage": round(coverage, 4),
            "new_content_ratio": round(new_content, 4),
            "chapter_growth": chapter_growth,
            "char_count_delta": char_count_delta,
            "quality_delta": round(quality_delta, 2),
            "recommendation": "manual_review",
            "reason": f"存在相似旧书《{best['title']}》（同书分 {same_work:.2f}），但新增内容证据不足，建议人工确认。",
            "risks": risks,
            "confidence": round(same_work * 0.9, 2),
            "update_type": "similar_only",
        }

    if same_work >= 0.75 or (same_work >= 0.70 and coverage >= 0.80):
        return {
            "classification": "manual_review",
            "classification_label": "需人工确认",
            "matched_book_id": best["book_id"],
            "matched_title": best["title"],
            "same_work_score": round(same_work, 4),
            "old_coverage": round(coverage, 4),
            "new_content_ratio": round(new_content, 4),
            "chapter_growth": chapter_growth,
            "char_count_delta": char_count_delta,
            "quality_delta": round(quality_delta, 2),
            "recommendation": "manual_review",
            "reason": f"根据标题、章节和字数判断，可能是新版；由于覆盖率未充分验证或存在风险，建议人工确认。",
            "risks": risks,
            "confidence": round(same_work * 0.9, 2),
            "update_type": "unknown",
        }

    return None


def _find_top_similar_library(conn, incoming_book: dict, library_books: list[dict], top_n: int = 3) -> list[dict]:
    """Find top N similar library books for an incoming book with full diagnostic info."""
    incoming_title = incoming_book.get("title_norm") or incoming_book.get("title_raw") or incoming_book.get("file_name")
    incoming_author = incoming_book.get("author_norm") or incoming_book.get("author_raw")
    incoming_chapters = int(incoming_book.get("chapter_count") or 0)
    incoming_chars = int(incoming_book.get("char_count_clean") or 0)

    scored = []
    for lib_book in library_books:
        lib_title = lib_book.get("title_norm") or lib_book.get("title_raw") or lib_book.get("file_name")
        lib_author = lib_book.get("author_norm") or lib_book.get("author_raw")
        lib_chapters = int(lib_book.get("chapter_count") or 0)
        lib_chars = int(lib_book.get("char_count_clean") or 0)

        title_score = title_similarity(incoming_title, lib_title)
        if title_score < 0.50:
            continue

        author_score = author_similarity(incoming_author, lib_author)
        chapter_growth = incoming_chapters - lib_chapters
        char_count_delta = incoming_chars - lib_chars

        try:
            incoming_ch_list = _chapters(conn, incoming_book["id"])
            lib_ch_list = _chapters(conn, lib_book["id"])
            comparison = compare_update_pair(conn, lib_book, incoming_book, lib_ch_list, incoming_ch_list)
            same_work = comparison.get("same_work_score", 0)
            coverage = comparison.get("coverage_score", 0)
            new_content = comparison.get("new_content_score", 0)
            quality_delta = comparison.get("quality_delta", 0)
        except Exception:
            same_work = title_score * 0.7
            coverage = 0.0
            new_content = 0.0
            quality_delta = 0.0

        decision = "no_match"
        reason = ""
        if same_work >= 0.85 and coverage >= 0.85 and (new_content >= 0.03 or chapter_growth >= 2):
            decision = "major_update"
            reason = "满足大幅更新条件"
        elif (same_work >= 0.88 or title_score >= 0.92) and coverage >= 0.90 and (chapter_growth >= 1 or new_content >= 0.005 or char_count_delta >= 500):
            decision = "minor_update"
            reason = "满足小幅更新条件"
        elif same_work >= 0.80:
            decision = "similar_only"
            reason = "高度相似但新增内容不足"
        elif same_work >= 0.70:
            decision = "possible_match"
            reason = "可能相似需人工确认"

        scored.append({
            "book_id": lib_book["id"],
            "title": lib_title,
            "title_score": round(title_score, 4),
            "author_score": round(author_score, 4),
            "same_work_score": round(same_work, 4),
            "old_coverage": round(coverage, 4),
            "new_content_ratio": round(new_content, 4),
            "char_count_delta": char_count_delta,
            "chapter_growth": chapter_growth,
            "quality_delta": round(quality_delta, 2),
            "decision": decision,
            "reason": reason,
        })

    scored.sort(key=lambda x: x["same_work_score"], reverse=True)
    return scored[:top_n]


def _find_in_update_report(conn: sqlite3.Connection, incoming_book_id: int) -> dict | None:
    try:
        row = conn.execute(
            "SELECT * FROM update_candidates WHERE new_book_id = ? ORDER BY same_work_score DESC LIMIT 1",
            (incoming_book_id,),
        ).fetchone()
        if row:
            return dict(row)
    except Exception:
        pass
    return None


def _find_in_duplicate_groups(conn: sqlite3.Connection, incoming_book_id: int) -> dict | None:
    try:
        row = conn.execute(
            """SELECT dgm.book_id AS matched_book_id, b.title_norm AS matched_title
               FROM duplicate_group_members dgm
               JOIN books b ON b.id = dgm.book_id
               WHERE dgm.duplicate_group_id IN (
                   SELECT duplicate_group_id FROM duplicate_group_members WHERE book_id = ?
               ) AND dgm.book_id != ? AND b.repo_area = 'library'
               LIMIT 1""",
            (incoming_book_id, incoming_book_id),
        ).fetchone()
        if row:
            return {
                "classification": "near_duplicate",
                "classification_label": "近似重复",
                "matched_book_id": row["matched_book_id"],
                "matched_title": row["matched_title"],
                "recommendation": "manual_review",
                "reason": "该文件与已有书籍高度相似，但不是完全一致。建议人工判断。",
                "confidence": 0.85,
                "risks": [],
            }
    except Exception:
        pass
    return None


def _save_analysis_report(repo: Path, report: dict) -> None:
    report_dir = repo / "reports" / "incoming"
    ensure_dir(report_dir)
    path = report_dir / f"incoming_analysis_{_ts_now()}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_log(repo, f"analyze_incoming saved report {path}")


def _empty_analysis() -> dict:
    return {"summary": {"incoming_count": 0, "new_book": 0, "exact_duplicate": 0, "update_candidate": 0, "near_duplicate": 0, "manual_review": 0, "reject": 0}, "items": []}


def _write_log(repo: Path, summary: str) -> None:
    log_dir = repo / "logs"
    ensure_dir(log_dir)
    with open(log_dir / "operations.log", "a", encoding="utf-8") as f:
        f.write(f"[{now_ts()}] {summary}\n")
