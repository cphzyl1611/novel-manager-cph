from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from novel_manager.server.services.upload_service import analyze_incoming


def _make_repo_for_analysis() -> Path:
    """Create a test repo with necessary tables and directories."""
    root = Path(tempfile.mkdtemp(prefix="test_incoming_analysis_"))
    for d in ["db", "library", "incoming", "reports/incoming", "logs"]:
        (root / d).mkdir(parents=True, exist_ok=True)

    db_path = root / "db" / "novel_repo.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY,
            title_raw TEXT,
            title_norm TEXT,
            author_raw TEXT,
            author_norm TEXT,
            file_name TEXT,
            current_path TEXT,
            repo_area TEXT,
            quality_score REAL,
            chapter_count INTEGER,
            char_count_clean INTEGER,
            char_count_raw INTEGER,
            raw_sha256 TEXT,
            clean_sha256 TEXT,
            ad_line_count INTEGER,
            mojibake_rate REAL,
            duplicate_chapter_count INTEGER,
            missing_chapter_count INTEGER,
            chapter_order_error_count INTEGER,
            status TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS chapters (
            id INTEGER PRIMARY KEY,
            book_id INTEGER,
            chapter_index INTEGER,
            chapter_no INTEGER,
            title_raw TEXT,
            title_norm TEXT,
            start_offset INTEGER,
            end_offset INTEGER,
            char_count INTEGER
        );
        CREATE TABLE IF NOT EXISTS update_candidates (
            id INTEGER PRIMARY KEY,
            old_book_id INTEGER,
            new_book_id INTEGER,
            same_work_score REAL,
            coverage_score REAL,
            new_content_score REAL,
            quality_delta REAL,
            old_chapter_count INTEGER,
            new_chapter_count INTEGER,
            recommendation TEXT,
            reason_summary TEXT,
            risk_flags TEXT
        );
        CREATE TABLE IF NOT EXISTS duplicate_groups (
            id INTEGER PRIMARY KEY,
            group_type TEXT
        );
        CREATE TABLE IF NOT EXISTS duplicate_group_members (
            duplicate_group_id INTEGER,
            book_id INTEGER
        );
    """)
    conn.commit()
    conn.close()
    return root


def _make_book(repo: Path, area: str, name: str, book_id: int, title: str, author: str = "",
               quality: float = 80.0, chapters: int = 100, chars: int = 100000,
               chapter_titles: list = None) -> Path:
    """Create a test book file and insert into database."""
    area_dir = repo / area
    area_dir.mkdir(parents=True, exist_ok=True)
    book_path = area_dir / name

    content = f"{title}\n作者：{author}\n\n"
    if chapter_titles:
        for i, ch_title in enumerate(chapter_titles):
            content += f"第{i+1}章 {ch_title}\n\n本章内容...\n\n"
    else:
        for i in range(chapters):
            content += f"第{i+1}章 章节标题{i+1}\n\n本章内容...\n\n"
    book_path.write_text(content, encoding="utf-8")

    db_path = repo / "db" / "novel_repo.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """INSERT INTO books (id, title_raw, title_norm, author_raw, author_norm, file_name, current_path, repo_area,
           quality_score, chapter_count, char_count_clean, char_count_raw, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'normal', '2024-01-01', '2024-01-01')""",
        (book_id, title, title, author, author, name, str(book_path), area, quality, chapters, chars, chars),
    )

    if chapter_titles:
        for i, ch_title in enumerate(chapter_titles):
            conn.execute(
                "INSERT INTO chapters (book_id, chapter_index, chapter_no, title_raw, title_norm) VALUES (?, ?, ?, ?, ?)",
                (book_id, i, i + 1, ch_title, ch_title),
            )
    else:
        for i in range(min(chapters, 50)):
            conn.execute(
                "INSERT INTO chapters (book_id, chapter_index, chapter_no, title_raw, title_norm) VALUES (?, ?, ?, ?, ?)",
                (book_id, i, i + 1, f"章节标题{i+1}", f"章节标题{i+1}"),
            )

    conn.commit()
    conn.close()
    return book_path


class TestIncomingAnalysisUpdateDetection:
    """Tests for incoming analysis update candidate detection."""

    def test_new_version_detected_as_update_candidate(self) -> None:
        """Test that a new version is detected as update_candidate, not new_book."""
        repo = _make_repo_for_analysis()

        old_chapters = [f"章节{i}" for i in range(1, 81)]
        new_chapters = old_chapters + [f"章节{i}" for i in range(81, 91)]

        _make_book(repo, "library", "old_book.txt", 1, "测试小说", "测试作者",
                   quality=75.0, chapters=80, chars=80000, chapter_titles=old_chapters)
        _make_book(repo, "incoming", "new_book.txt", 2, "测试小说", "测试作者",
                   quality=80.0, chapters=90, chars=90000, chapter_titles=new_chapters)

        result = analyze_incoming(str(repo))

        assert result["summary"]["incoming_count"] == 1
        assert result["summary"]["update_candidate"] == 1, f"Expected update_candidate=1, got {result['summary']}"
        assert result["summary"]["new_book"] == 0, f"Expected new_book=0, got {result['summary']}"

        item = result["items"][0]
        assert item["classification"] == "update_candidate"
        assert item["matched_book_id"] == 1
        assert item["same_work_score"] is not None
        assert item["same_work_score"] >= 0.85

    def test_truly_new_book_detected_as_new_book(self) -> None:
        """Test that a truly new book is detected as new_book."""
        repo = _make_repo_for_analysis()

        _make_book(repo, "library", "old_book.txt", 1, "完全不同的书", "作者A",
                   quality=80.0, chapters=50, chars=50000)
        _make_book(repo, "incoming", "new_book.txt", 2, "另一本完全不同的书", "作者B",
                   quality=85.0, chapters=60, chars=60000)

        result = analyze_incoming(str(repo))

        assert result["summary"]["incoming_count"] == 1
        assert result["summary"]["new_book"] == 1

        item = result["items"][0]
        assert item["classification"] == "new_book"
        assert item["matched_book_id"] is None

    def test_exact_duplicate_detected(self) -> None:
        """Test that exact duplicates are detected."""
        repo = _make_repo_for_analysis()

        book_path = _make_book(repo, "library", "book.txt", 1, "测试小说", "测试作者",
                               quality=80.0, chapters=50, chars=50000)

        db_path = repo / "db" / "novel_repo.sqlite"
        conn = sqlite3.connect(str(db_path))
        content = book_path.read_text(encoding="utf-8")
        import hashlib
        raw_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        conn.execute("UPDATE books SET raw_sha256 = ? WHERE id = 1", (raw_hash,))
        conn.execute(
            "INSERT INTO books (id, title_raw, title_norm, file_name, current_path, repo_area, quality_score, chapter_count, char_count_clean, raw_sha256, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'normal', '2024-01-01', '2024-01-01')",
            (2, "测试小说", "测试小说", "book_copy.txt", str(repo / "incoming" / "book_copy.txt"), "incoming", 80.0, 50, 50000, raw_hash),
        )
        (repo / "incoming" / "book_copy.txt").write_text(content, encoding="utf-8")
        conn.commit()
        conn.close()

        result = analyze_incoming(str(repo))

        assert result["summary"]["exact_duplicate"] == 1
        item = result["items"][0]
        assert item["classification"] == "exact_duplicate"

    def test_author_conflict_goes_to_manual_review(self) -> None:
        """Test that author conflict results in manual_review, not new_book."""
        repo = _make_repo_for_analysis()

        old_chapters = [f"章节{i}" for i in range(1, 81)]
        new_chapters = old_chapters + [f"章节{i}" for i in range(81, 91)]

        _make_book(repo, "library", "old_book.txt", 1, "测试小说", "作者A",
                   quality=75.0, chapters=80, chars=80000, chapter_titles=old_chapters)
        _make_book(repo, "incoming", "new_book.txt", 2, "测试小说", "作者B",
                   quality=80.0, chapters=90, chars=90000, chapter_titles=new_chapters)

        result = analyze_incoming(str(repo))

        assert result["summary"]["incoming_count"] == 1
        assert result["summary"]["new_book"] == 0, f"Should not be new_book, got {result['summary']}"

        item = result["items"][0]
        assert item["classification"] in ["manual_review", "update_candidate"], f"Got {item['classification']}"
        assert "author" in " ".join(item.get("risks", [])).lower() or item["classification"] == "manual_review"

    def test_shorter_new_version_not_replace_recommended(self) -> None:
        """Test that shorter new version is not recommended for replace."""
        repo = _make_repo_for_analysis()

        old_chapters = [f"章节{i}" for i in range(1, 101)]
        new_chapters = [f"章节{i}" for i in range(1, 51)]

        _make_book(repo, "library", "old_book.txt", 1, "测试小说", "测试作者",
                   quality=75.0, chapters=100, chars=100000, chapter_titles=old_chapters)
        _make_book(repo, "incoming", "new_book.txt", 2, "测试小说", "测试作者",
                   quality=80.0, chapters=50, chars=50000, chapter_titles=new_chapters)

        result = analyze_incoming(str(repo))

        item = result["items"][0]
        assert item["classification"] in ["manual_review", "new_book"], f"Got {item['classification']}"

    def test_analysis_saves_report(self) -> None:
        """Test that analysis saves JSON report."""
        repo = _make_repo_for_analysis()

        _make_book(repo, "incoming", "new_book.txt", 1, "测试小说", "测试作者")

        result = analyze_incoming(str(repo))

        assert result["summary"]["incoming_count"] == 1

        report_dir = repo / "reports" / "incoming"
        json_files = list(report_dir.glob("*.json"))
        assert len(json_files) >= 1

    def test_no_file_modification(self) -> None:
        """Test that analysis does not modify or move files."""
        repo = _make_repo_for_analysis()

        old_book = _make_book(repo, "library", "old_book.txt", 1, "测试小说", "测试作者",
                              quality=75.0, chapters=80, chars=80000)
        new_book = _make_book(repo, "incoming", "new_book.txt", 2, "测试小说", "测试作者",
                              quality=80.0, chapters=90, chars=90000)

        old_content = old_book.read_text(encoding="utf-8")
        new_content = new_book.read_text(encoding="utf-8")

        analyze_incoming(str(repo))

        assert old_book.exists()
        assert new_book.exists()
        assert old_book.read_text(encoding="utf-8") == old_content
        assert new_book.read_text(encoding="utf-8") == new_content

    def test_top_matches_included_for_new_book(self) -> None:
        """Test that top_matches is included even for new_book classification."""
        repo = _make_repo_for_analysis()

        _make_book(repo, "library", "similar_book.txt", 1, "相似的书名", "测试作者",
                   quality=75.0, chapters=80, chars=80000)
        _make_book(repo, "incoming", "new_book.txt", 2, "相似的书名新版本", "测试作者",
                   quality=80.0, chapters=90, chars=90000)

        result = analyze_incoming(str(repo))

        item = result["items"][0]
        assert "top_matches" in item
        if item["classification"] == "new_book":
            assert len(item["top_matches"]) >= 1

    def test_minor_single_chapter_update_detected(self) -> None:
        """Test that a minor update with only one new chapter is detected as update_candidate."""
        repo = _make_repo_for_analysis()

        old_chapters = [f"章节{i}" for i in range(1, 4)]
        new_chapters = old_chapters + ["章节4"]

        _make_book(repo, "library", "old_book.txt", 1, "测试小说", "测试作者",
                   quality=80.0, chapters=3, chars=3000, chapter_titles=old_chapters)
        _make_book(repo, "incoming", "new_book.txt", 2, "测试小说", "测试作者",
                   quality=80.0, chapters=4, chars=3500, chapter_titles=new_chapters)

        result = analyze_incoming(str(repo))

        assert result["summary"]["incoming_count"] == 1
        assert result["summary"]["update_candidate"] == 1, f"Expected update_candidate=1, got {result['summary']}"
        assert result["summary"]["new_book"] == 0, f"Expected new_book=0, got {result['summary']}"

        item = result["items"][0]
        assert item["classification"] == "update_candidate"
        assert item.get("update_type") == "minor_update"
        assert item["recommendation"] == "manual_review"
        assert item["chapter_growth"] == 1

    def test_formatting_only_change_not_update_candidate(self) -> None:
        """Test that formatting-only changes without new content are not update_candidate."""
        repo = _make_repo_for_analysis()

        chapters = [f"章节{i}" for i in range(1, 51)]

        _make_book(repo, "library", "old_book.txt", 1, "测试小说", "测试作者",
                   quality=80.0, chapters=50, chars=50000, chapter_titles=chapters)
        _make_book(repo, "incoming", "new_book.txt", 2, "测试小说", "测试作者",
                   quality=80.0, chapters=50, chars=50000, chapter_titles=chapters)

        result = analyze_incoming(str(repo))

        item = result["items"][0]
        assert item["classification"] in ["manual_review", "near_duplicate"], f"Got {item['classification']}"
        assert item["classification"] != "new_book"

    def test_same_title_different_content_is_manual_review(self) -> None:
        """Test that same title but different content goes to manual_review, not update_candidate."""
        repo = _make_repo_for_analysis()

        old_chapters = [f"旧章节{i}" for i in range(1, 51)]
        new_chapters = [f"新章节{i}" for i in range(1, 51)]

        _make_book(repo, "library", "old_book.txt", 1, "测试小说", "测试作者",
                   quality=80.0, chapters=50, chars=50000, chapter_titles=old_chapters)
        _make_book(repo, "incoming", "new_book.txt", 2, "测试小说", "测试作者",
                   quality=80.0, chapters=50, chars=50000, chapter_titles=new_chapters)

        result = analyze_incoming(str(repo))

        item = result["items"][0]
        assert item["classification"] in ["manual_review", "new_book"], f"Got {item['classification']}"
        if item["classification"] == "update_candidate":
            assert item.get("update_type") != "major_update"

    def test_top_matches_contains_char_count_delta(self) -> None:
        """Test that top_matches includes char_count_delta and chapter_growth."""
        repo = _make_repo_for_analysis()

        _make_book(repo, "library", "old_book.txt", 1, "测试小说", "测试作者",
                   quality=80.0, chapters=50, chars=50000)
        _make_book(repo, "incoming", "new_book.txt", 2, "测试小说", "测试作者",
                   quality=85.0, chapters=55, chars=55000)

        result = analyze_incoming(str(repo))

        item = result["items"][0]
        assert "top_matches" in item
        if item["top_matches"]:
            top = item["top_matches"][0]
            assert "char_count_delta" in top
            assert "chapter_growth" in top
            assert "decision" in top
            assert "reason" in top

    def test_high_similarity_without_new_content_is_manual_review(self) -> None:
        """Test that high similarity but no new content goes to manual_review, not new_book."""
        repo = _make_repo_for_analysis()

        chapters = [f"章节{i}" for i in range(1, 81)]

        _make_book(repo, "library", "old_book.txt", 1, "测试小说", "测试作者",
                   quality=80.0, chapters=80, chars=80000, chapter_titles=chapters)
        _make_book(repo, "incoming", "new_book.txt", 2, "测试小说", "测试作者",
                   quality=82.0, chapters=80, chars=80500, chapter_titles=chapters)

        result = analyze_incoming(str(repo))

        item = result["items"][0]
        assert item["classification"] != "new_book", f"Should not be new_book, got {item['classification']}"
        assert item["same_work_score"] is not None
        assert item["same_work_score"] >= 0.80
