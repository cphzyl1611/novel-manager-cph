"""Mobile API service — per-chapter data for native Android reader."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ...db import connect as db_connect
from .book_service import _is_current_library_book, _ensure_progress_table
from .progress_service import save_progress

VIRTUAL_CHAPTER_SIZE = 40000  # chars per virtual chapter when no real chapters exist


def get_mobile_books(repo_path: str) -> dict[str, Any]:
    """Return valid library books for mobile shelf."""
    root = Path(repo_path).expanduser().resolve()
    _ensure_progress_table(root)
    try:
        conn = db_connect(root)
    except Exception:
        return {"items": [], "server_revision": 0}

    try:
        rows = conn.execute("""
            SELECT b.id AS book_id, b.title_norm AS title, b.author_norm AS author,
                   b.chapter_count, b.quality_score, b.repo_area, b.current_path, b.status,
                   rpl.latest_read_at, rp.progress_ratio
            FROM books b
            LEFT JOIN (SELECT book_id, MAX(updated_at) AS latest_read_at
                       FROM reading_progress GROUP BY book_id) rpl ON rpl.book_id = b.id
            LEFT JOIN reading_progress rp ON rp.book_id = b.id AND rp.device_id = 'web'
            WHERE b.repo_area = 'library'
              AND (b.status IS NULL OR b.status NOT IN ('external_removed','ignored_missing'))
            ORDER BY CASE WHEN rpl.latest_read_at IS NULL THEN 1 ELSE 0 END,
                     rpl.latest_read_at DESC, b.updated_at DESC
        """).fetchall()

        items = []
        for r in rows:
            d = dict(r)
            if _is_current_library_book(root, d):
                items.append({
                    "book_id": d["book_id"],
                    "title": d["title"] or "",
                    "author": d["author"] or "",
                    "chapter_count": d["chapter_count"] or 0,
                    "quality_score": d["quality_score"],
                    "latest_read_at": d["latest_read_at"],
                    "progress_ratio": float(d["progress_ratio"]) if d["progress_ratio"] else 0.0,
                })

        revision = 0
        try:
            rev = conn.execute("SELECT server_revision FROM sync_state WHERE id=1").fetchone()
            if rev: revision = rev[0]
        except Exception: pass

        conn.close()
        return {"items": items, "server_revision": revision}
    except Exception:
        conn.close()
        return {"items": [], "server_revision": 0}


def get_mobile_chapters(repo_path: str, book_id: int) -> dict[str, Any] | None:
    """Return chapter list for a book. Creates virtual chapters for books without real ones."""
    root = Path(repo_path).expanduser().resolve()
    try: conn = db_connect(root)
    except Exception: return None
    try:
        book = conn.execute(
            "SELECT id, title_norm, current_path FROM books WHERE id=?", (book_id,)
        ).fetchone()
        if not book: conn.close(); return None

        rows = conn.execute(
            "SELECT chapter_index, title_raw, start_offset, end_offset, char_count "
            "FROM chapters WHERE book_id=? ORDER BY chapter_index", (book_id,)
        ).fetchall()
        conn.close()

        if rows:
            chapters = [{"index": r["chapter_index"],
                         "title": r["title_raw"] or f"Chapter {r['chapter_index']+1}",
                         "char_count": r["char_count"] or 0} for r in rows]
            return {"book_id": book_id, "title": book["title_norm"] or "",
                    "chapters": chapters, "note": None}

        # No real chapters — try parsing or create virtual chapters
        book_path = book["current_path"]
        if not book_path or not Path(book_path).exists():
            return {"book_id": book_id, "title": book["title_norm"] or "",
                    "chapters": [], "note": "file_missing"}

        try:
            from ...chapter_parser import parse_chapters
            content = Path(book_path).read_text(encoding="utf-8", errors="replace")
            parsed = parse_chapters(content)
            if parsed.chapters:
                chapters = [{"index": i, "title": c["title_raw"], "char_count": 0}
                            for i, c in enumerate(parsed.chapters)]
                return {"book_id": book_id, "title": book["title_norm"] or "",
                        "chapters": chapters, "note": "parsed"}
        except Exception: pass

        # No chapters found — create virtual chapters
        fc = _read_full_with_encoding(book_path); content = fc[0] if fc else ""
        total_len = len(content)
        if total_len == 0:
            return {"book_id": book_id, "title": book["title_norm"] or "",
                    "chapters": [], "note": "empty"}

        vc_count = max(1, (total_len + VIRTUAL_CHAPTER_SIZE - 1) // VIRTUAL_CHAPTER_SIZE)
        chapters = [{"index": i, "title": f"Part {i+1}",
                     "char_count": VIRTUAL_CHAPTER_SIZE} for i in range(vc_count)]
        return {"book_id": book_id, "title": book["title_norm"] or "",
                "chapters": chapters, "note": "virtual",
                "total_chars": total_len}
    except Exception:
        try: conn.close()
        except Exception: pass
        return None


def get_mobile_chapter_content(repo_path: str, book_id: int,
                                chapter_index: int) -> dict[str, Any] | None:
    """Return single chapter content. Never returns truncated full book."""
    root = Path(repo_path).expanduser().resolve()
    try: conn = db_connect(root)
    except Exception: return None
    try:
        book = conn.execute(
            "SELECT id, title_norm, current_path FROM books WHERE id=?", (book_id,)
        ).fetchone()
        if not book: conn.close(); return None

        book_path = book["current_path"]
        if not book_path or not Path(book_path).exists():
            conn.close()
            return {"book_id": book_id, "chapter_index": chapter_index,
                    "title": "", "content": "", "error": "file_missing"}

        ch_rows = conn.execute(
            "SELECT chapter_index, title_raw, start_offset, end_offset "
            "FROM chapters WHERE book_id=? ORDER BY chapter_index", (book_id,)
        ).fetchall()
        chapters = [dict(r) for r in ch_rows]
        conn.close()

        if chapters and chapter_index < len(chapters):
            ch = _extract_real_chapter(book_path, chapter_index, chapters)
            prev_idx = chapter_index - 1 if chapter_index > 0 else None
            next_idx = chapter_index + 1 if chapter_index + 1 < len(chapters) else None
            total = len(chapters)
            note = None
        else:
            # Virtual chapter from full content
            ch = _extract_virtual_chapter(book_path, chapter_index)
            total = _virtual_chapter_count(book_path)
            prev_idx = chapter_index - 1 if chapter_index > 0 else None
            next_idx = chapter_index + 1 if chapter_index + 1 < total else None
            note = "virtual"

        if ch is None:
            return {"book_id": book_id, "chapter_index": chapter_index,
                    "title": "", "content": "", "error": "extract_failed",
                    "prev": prev_idx, "next": next_idx, "total_chapters": total}

        content_text = ch.get("content", "") if ch else ""
        return {"book_id": book_id, "chapter_index": chapter_index,
                "title": ch.get("title", "") if ch else "", "content": content_text,
                "content_length": len(content_text),
                "encoding": ch.get("encoding", "") if ch else "",
                "prev": prev_idx, "next": next_idx, "total_chapters": total,
                "note": note,
                "start_char": ch.get("start_char") if ch else None,
                "end_char": ch.get("end_char") if ch else None}
    except Exception:
        try: conn.close()
        except Exception: pass
        return None


def _extract_real_chapter(file_path: str, idx: int, chapters: list[dict]) -> dict | None:
    """Extract one real chapter by byte offset. Last chapter reads to file end for encoding."""
    try:
        ch = chapters[idx]
        start = ch["start_offset"]
        end = ch.get("end_offset")
        # If next chapter exists, use its start_offset as end boundary
        if not end and idx + 1 < len(chapters):
            end = chapters[idx + 1].get("start_offset")

        with open(file_path, "rb") as f:
            f.seek(start)
            if end and end > start:
                raw = f.read(end - start)
            else:
                raw = f.read()  # Last chapter: read to file end

        # Detect encoding: read a small portion for detection
        from .text_reader import read_text_safely
        result = read_text_safely(Path(file_path), max_bytes=None)
        encoding = result.get("encoding", "")
        try:
            content = raw.decode(encoding or "utf-8", errors="replace")
        except Exception:
            content = raw.decode("utf-8", errors="replace")
        return {"title": ch.get("title_raw", ""), "content": content,
                "encoding": encoding, "start_char": None, "end_char": None}
    except Exception:
        return None


def _read_full_with_encoding(file_path: str) -> tuple[str, str] | None:
    """Read entire file and detect encoding."""
    try:
        from charset_normalizer import from_path
        results = from_path(file_path)
        if results:
            best = results.best()
            if best:
                return str(best), best.encoding or "utf-8"
        # Fallback: try utf-8
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        return content, "utf-8"
    except Exception:
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
            return content, "utf-8"
        except Exception:
            return None


def _virtual_chapter_count(file_path: str) -> int:
    """Count virtual chapters for a file."""
    try:
        result = _read_full_with_encoding(file_path)
        if not result: return 1
        content, _ = result
        return max(1, (len(content) + VIRTUAL_CHAPTER_SIZE - 1) // VIRTUAL_CHAPTER_SIZE)
    except Exception:
        return 1


def _extract_virtual_chapter(file_path: str, idx: int) -> dict | None:
    """Extract a virtual chapter slice from full file content."""
    try:
        result = _read_full_with_encoding(file_path)
        if not result: return None
        content, encoding = result
        start = idx * VIRTUAL_CHAPTER_SIZE
        end = start + VIRTUAL_CHAPTER_SIZE
        chunk = content[start:end]
        if not chunk:
            return None
        return {"title": f"Part {idx + 1}", "content": chunk, "encoding": encoding,
                "start_char": start, "end_char": end}
    except Exception:
        return None


def save_mobile_progress(repo_path: str, payload: dict) -> dict[str, Any]:
    """Save reading progress from mobile device."""
    book_id = payload.get("book_id")
    if not book_id: return {"ok": False, "error": "missing book_id"}
    chapter_index = max(0, int(payload.get("chapter_index", 0)))
    progress_ratio = max(0.0, min(1.0, float(payload.get("progress_ratio", 0))))
    scroll_position = max(0, int(payload.get("scroll_position", 0)))
    device_id = str(payload.get("device_id", "android"))
    return save_progress(repo_path, book_id, progress_ratio, scroll_position,
                         device_id, chapter_index)
