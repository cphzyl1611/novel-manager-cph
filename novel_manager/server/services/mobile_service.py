"""Mobile API service — per-chapter data for native Android reader."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ...db import connect as db_connect
from .book_service import _is_current_library_book, _ensure_progress_table
from .progress_service import save_progress


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
    """Return chapter list for a book."""
    root = Path(repo_path).expanduser().resolve()
    try: conn = db_connect(root)
    except Exception: return None
    try:
        book = conn.execute(
            "SELECT id, title_norm, current_path, chapter_count FROM books WHERE id=?", (book_id,)
        ).fetchone()
        if not book: conn.close(); return None

        rows = conn.execute(
            "SELECT chapter_index, title_raw, start_offset, end_offset, char_count "
            "FROM chapters WHERE book_id=? ORDER BY chapter_index", (book_id,)
        ).fetchall()

        chapters = []
        for r in rows:
            chapters.append({"index": r["chapter_index"],
                             "title": r["title_raw"] or f"Chapter {r['chapter_index']+1}",
                             "char_count": r["char_count"] or 0})

        if not chapters and book["current_path"]:
            try:
                from ...chapter_parser import parse_chapters
                content = Path(book["current_path"]).read_text(encoding="utf-8", errors="replace")
                parsed = parse_chapters(content)
                if parsed.chapters:
                    chapters = [{"index": i, "title": c["title_raw"], "char_count": 0}
                                for i, c in enumerate(parsed.chapters)]
            except Exception: pass

        conn.close()
        return {"book_id": book_id, "title": book["title_norm"] or "",
                "chapters": chapters, "note": "single_chapter" if not chapters else None}
    except Exception:
        conn.close(); return None


def get_mobile_chapter_content(repo_path: str, book_id: int,
                                chapter_index: int) -> dict[str, Any] | None:
    """Return single chapter content. Never returns full book."""
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
        total = len(chapters)
        conn.close()

        ch = _extract_chapter(book_path, chapter_index, chapters, total)
        prev_idx = chapter_index - 1 if chapter_index > 0 else None
        next_idx = chapter_index + 1 if chapter_index + 1 < max(total, 1) else None

        return {"book_id": book_id, "chapter_index": chapter_index,
                "title": ch.get("title", "") if ch else "",
                "content": ch.get("content", "") if ch else "",
                "encoding": ch.get("encoding", "") if ch else "",
                "prev": prev_idx, "next": next_idx,
                "total_chapters": max(total, 1),
                "single_chapter": total == 0}
    except Exception:
        try: conn.close()
        except Exception: pass
        return None


def _extract_chapter(file_path: str, idx: int, chapters: list[dict], total: int) -> dict | None:
    """Extract one chapter by byte offset from TXT."""
    try:
        from .text_reader import read_text_safely

        if total == 0:
            # No chapters — read file, return a per-call chunk to avoid full book
            result = read_text_safely(Path(file_path), max_bytes=2000000)
            content = result["text"]
            encoding = result.get("encoding", "")
            seg_size = 50000
            start_off = idx * seg_size
            chunk = content[start_off:start_off + seg_size]
            return {"title": f"Part {idx + 1}", "content": chunk, "encoding": encoding}

        ch = chapters[idx]
        start = ch["start_offset"]
        end = ch.get("end_offset")

        with open(file_path, "rb") as f:
            f.seek(start)
            chunk_size = (end - start) if (end and end > start) else 2000000
            raw = f.read(min(chunk_size, 2000000))

        result = read_text_safely(Path(file_path), max_bytes=2000000)
        encoding = result.get("encoding", "")
        content = raw.decode(encoding or "utf-8", errors="replace")
        return {"title": ch.get("title_raw", ""), "content": content, "encoding": encoding}
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
