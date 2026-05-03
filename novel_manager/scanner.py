from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from charset_normalizer import from_bytes

from .chapter_parser import parse_chapters
from .config import load_cleaning_rules
from .db import insert_scan_error, replace_chapters, upsert_book
from .fingerprint import normalize_author, normalize_title, sha256_file, sha256_text
from .quality import score_quality
from .text_cleaner import clean_text
from .utils import now_ts


AREA_DIRS = {"library": ["library"], "incoming": ["incoming"], "all": ["library", "incoming"]}


def detect_and_decode(raw: bytes) -> tuple[str, str, float, str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig", 1.0, "ok"
    matches = from_bytes(raw)
    best = matches.best()
    if best and best.encoding:
        try:
            return str(best), best.encoding, float(best.percent_coherence or 0) / 100, "ok"
        except Exception:
            pass
    errors: list[str] = []
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc), enc, 0.0, "fallback"
        except UnicodeDecodeError as exc:
            errors.append(f"{enc}: {exc}")
    raise UnicodeDecodeError("unknown", raw[:20], 0, 1, "; ".join(errors))


def iter_txt_files(repo: Path, area: str, limit: int | None = None) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for area_dir in AREA_DIRS[area]:
        root = repo / area_dir
        if not root.exists():
            continue
        for path in root.rglob("*.txt"):
            if path.is_file():
                files.append((area_dir, path))
                if limit and len(files) >= limit:
                    return files
    return files


def extract_metadata(path: Path, text: str) -> tuple[str, str | None, str, str]:
    stem = path.stem
    author = None
    title = stem
    author_match = re.search(r"作者\s*[:：]\s*([^\s\]】）)]+)", stem)
    if not author_match:
        author_match = re.search(r"作者\s*[:：]\s*([^\n\r]{1,40})", text[:2000])
    if author_match:
        author = author_match.group(1).strip()
        title = re.sub(r"作者\s*[:：]\s*[^\s\]】）)]+", "", stem).strip()
    title = title.strip(" 《》[]【】()（）")
    return title, author, normalize_title(title), normalize_author(author)


def should_skip(conn: sqlite3.Connection, path: Path, changed_only: bool, force: bool) -> bool:
    if force or not changed_only:
        return False
    stat = path.stat()
    row = conn.execute(
        "SELECT file_size, mtime FROM books WHERE current_path = ? ORDER BY id DESC LIMIT 1",
        (str(path),),
    ).fetchone()
    if not row:
        return False
    return int(row["file_size"] or -1) == stat.st_size and float(row["mtime"] or -1) == stat.st_mtime


def scan_file(conn: sqlite3.Connection, repo: Path, area: str, path: Path, dry_run: bool = False) -> dict[str, Any]:
    try:
        stat = path.stat()
        if stat.st_size == 0:
            raise ValueError("empty file")
        raw_bytes = path.read_bytes()
        text, encoding, confidence, decode_status = detect_and_decode(raw_bytes)
        raw_hash = sha256_file(path)
        rules = load_cleaning_rules(repo)
        cleaned, metrics = clean_text(text, rules.get("ad_keywords"))
        clean_hash = sha256_text(cleaned)
        title_raw, author_raw, title_norm, author_norm = extract_metadata(path, text)
        chapter_result = parse_chapters(cleaned)
        quality = score_quality(
            char_count_clean=metrics.char_count_clean,
            chapter_count=len(chapter_result.chapters),
            mojibake_rate=metrics.mojibake_rate,
            ad_line_count=metrics.ad_line_count,
            ad_line_rate=metrics.ad_line_rate,
            duplicate_chapter_count=chapter_result.duplicate_chapter_count,
            missing_chapter_count=chapter_result.missing_chapter_count,
            chapter_order_error_count=chapter_result.chapter_order_error_count,
            file_name=path.name,
            title_norm=title_norm,
            author_norm=author_norm,
        )
        data = {
            "current_path": str(path),
            "original_path": str(path),
            "repo_area": area,
            "file_name": path.name,
            "file_size": stat.st_size,
            "mtime": stat.st_mtime,
            "raw_sha256": raw_hash,
            "clean_sha256": clean_hash,
            "title_raw": title_raw,
            "title_norm": title_norm,
            "author_raw": author_raw,
            "author_norm": author_norm,
            "encoding": encoding,
            "encoding_confidence": confidence,
            "decode_status": decode_status,
            "char_count_raw": metrics.char_count_raw,
            "char_count_clean": metrics.char_count_clean,
            "line_count_raw": metrics.line_count_raw,
            "line_count_clean": metrics.line_count_clean,
            "chapter_count": len(chapter_result.chapters),
            "mojibake_rate": metrics.mojibake_rate,
            "ad_line_count": metrics.ad_line_count,
            "ad_line_rate": metrics.ad_line_rate,
            "duplicate_chapter_count": chapter_result.duplicate_chapter_count,
            "missing_chapter_count": chapter_result.missing_chapter_count,
            "chapter_order_error_count": chapter_result.chapter_order_error_count,
            "truncated_risk": quality.truncated_risk,
            "quality_score": quality.quality_score,
            "quality_level": quality.quality_level,
            "quality_reasons_json": json.dumps(quality.quality_reasons, ensure_ascii=False),
            "status": "active",
            "reading_status": None,
            "created_at": now_ts(),
            "updated_at": now_ts(),
        }
        if dry_run:
            return {"path": str(path), "status": "dry_run", "book": data}
        book_id = upsert_book(conn, data)
        replace_chapters(conn, book_id, chapter_result.chapters)
        return {"path": str(path), "status": "scanned", "book_id": book_id}
    except PermissionError as exc:
        if not dry_run:
            insert_scan_error(conn, str(path), area, "permission_error", str(exc))
        return {"path": str(path), "status": "error", "error": str(exc)}
    except Exception as exc:
        if not dry_run:
            insert_scan_error(conn, str(path), area, type(exc).__name__, str(exc))
        return {"path": str(path), "status": "error", "error": str(exc)}


def scan_repo(
    conn: sqlite3.Connection,
    repo: Path,
    area: str,
    changed_only: bool = False,
    force: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    stats = {"found": 0, "scanned": 0, "skipped": 0, "errors": 0}
    for repo_area, path in iter_txt_files(repo, area, limit):
        stats["found"] += 1
        try:
            if should_skip(conn, path, changed_only, force):
                stats["skipped"] += 1
                continue
            result = scan_file(conn, repo, repo_area, path, dry_run=dry_run)
            if result["status"] in {"scanned", "dry_run"}:
                stats["scanned"] += 1
            else:
                stats["errors"] += 1
        except Exception as exc:
            stats["errors"] += 1
            if not dry_run:
                insert_scan_error(conn, str(path), repo_area, type(exc).__name__, str(exc))
    return stats
