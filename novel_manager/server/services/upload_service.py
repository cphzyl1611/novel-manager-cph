from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from ...db import connect as db_connect
from ...scanner import scan_file
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
    root = Path(repo_path).expanduser().resolve()
    try:
        conn = db_connect(root)
        conn.row_factory = sqlite3.Row
        incoming_books = conn.execute("SELECT * FROM books WHERE repo_area = 'incoming'").fetchall()
        if not incoming_books:
            conn.close()
            return _empty_analysis()
        library_books = conn.execute(
            "SELECT id, file_name, title_norm, author_norm, raw_sha256, clean_sha256, char_count_clean, chapter_count, quality_score, current_path FROM books WHERE repo_area = 'library'"
        ).fetchall()
    except Exception:
        return _empty_analysis()
    lib_by_raw = {r["raw_sha256"]: dict(r) for r in library_books if r["raw_sha256"]}
    lib_by_clean = {r["clean_sha256"]: dict(r) for r in library_books if r["clean_sha256"]}

    items: list[dict] = []
    summary = {"incoming_count": len(incoming_books), "new_book": 0, "exact_duplicate": 0, "update_candidate": 0, "near_duplicate": 0, "manual_review": 0, "reject": 0}

    for ib in incoming_books:
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
        elif clean_hash and clean_hash in lib_by_clean:
            matched = lib_by_clean[clean_hash]
            item["classification"] = "exact_duplicate"
            item["classification_label"] = "简单重复（清洗后）"
            item["recommendation"] = "duplicate_review"
            item["reason"] = "去除广告后内容相同的文件已存在。"
            item["confidence"] = 0.99

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

        summary[item["classification"]] = summary.get(item["classification"], 0) + 1
        items.append(item)

    conn.close()

    report = {"summary": summary, "items": items, "generated_at": now_ts(), "repo_path": str(root), "algorithm_version": "1.0"}
    _save_analysis_report(root, report)
    return report


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
