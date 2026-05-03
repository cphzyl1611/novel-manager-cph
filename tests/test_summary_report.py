import json
import uuid
from pathlib import Path

from novel_manager.summary_report import generate_summary_report


def make_repo() -> Path:
    root = Path(".tmp") / "summary_tests" / uuid.uuid4().hex
    (root / "reports" / "duplicate").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "quality").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "errors").mkdir(parents=True, exist_ok=True)
    return root


def write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def sample_duplicate(path: Path) -> Path:
    return write_json(
        path,
        {
            "generated_at": "20260501_010101",
            "groups": [
                {
                    "id": 1,
                    "group_type": "raw_exact",
                    "confidence": 1.0,
                    "recommended_keep_book_id": 1,
                    "reason_summary": "A.txt 质量分更高，位于 library。",
                    "members": [
                        {
                            "suggested_role": "keep",
                            "reason": "推荐保留",
                            "book": {
                                "id": 1,
                                "current_path": "D:/NovelRepo_Test/library/A.txt",
                                "file_name": "A.txt",
                                "quality_score": 90.0,
                            },
                        },
                        {
                            "suggested_role": "archive_candidate",
                            "reason": "可移动到 review_duplicates",
                            "book": {
                                "id": 2,
                                "current_path": "D:/NovelRepo_Test/library/A_copy.txt",
                                "file_name": "A_copy.txt",
                                "quality_score": 85.0,
                            },
                        },
                    ],
                }
            ],
        },
    )


def sample_quality(path: Path) -> Path:
    return write_json(
        path,
        {
            "generated_at": "20260501_010101",
            "area": "all",
            "books": [
                {
                    "id": 3,
                    "current_path": "D:/NovelRepo_Test/library/A_ad.txt",
                    "file_name": "A_ad.txt",
                    "quality_score": 42.0,
                    "quality_level": "poor",
                    "chapter_count": 3,
                    "ad_line_count": 100,
                    "mojibake_rate": 0.0,
                    "duplicate_chapter_count": 0,
                    "missing_chapter_count": 2,
                    "chapter_order_error_count": 0,
                    "truncated_risk": 1,
                    "quality_reasons": ["广告行较多，质量扣分", "检测到疑似缺章"],
                }
            ],
        },
    )


def sample_errors(path: Path) -> Path:
    return write_json(
        path,
        {
            "generated_at": "20260501_010101",
            "errors": [
                {
                    "file_path": "D:/NovelRepo_Test/library/A_bad_encoding.txt",
                    "repo_area": "library",
                    "error_type": "UnicodeDecodeError",
                    "error_message": "decode failed",
                }
            ],
        },
    )


def test_summary_from_duplicate_report_json():
    repo = make_repo()
    duplicate = sample_duplicate(repo / "reports" / "duplicate" / "duplicate_report_20260501_010101.json")
    output = generate_summary_report(repo, duplicate_report=duplicate)
    text = output.read_text(encoding="utf-8")
    assert "小说库整理汇总报告" in text
    assert "重复检测汇总" in text
    assert "raw_exact" in text
    assert "A_copy.txt" in text


def test_summary_from_quality_report_json():
    repo = make_repo()
    quality = sample_quality(repo / "reports" / "quality" / "quality_report_20260501_010101.json")
    output = generate_summary_report(repo, quality_report=quality)
    text = output.read_text(encoding="utf-8")
    assert "质量问题汇总" in text
    assert "A_ad.txt" in text
    assert "广告行较多" in text


def test_summary_from_error_report_json():
    repo = make_repo()
    error = sample_errors(repo / "reports" / "errors" / "scan_error_report_20260501_010101.json")
    output = generate_summary_report(repo, error_report=error)
    text = output.read_text(encoding="utf-8")
    assert "扫描错误汇总" in text
    assert "UnicodeDecodeError" in text
    assert "A_bad_encoding.txt" in text


def test_summary_missing_report_does_not_crash():
    repo = make_repo()
    output = generate_summary_report(repo, duplicate_report=repo / "missing.json")
    text = output.read_text(encoding="utf-8")
    assert "报告文件不存在" in text
    assert "建议下一步操作" in text


def test_summary_contains_required_sections():
    repo = make_repo()
    sample_duplicate(repo / "reports" / "duplicate" / "duplicate_report_20260501_010101.json")
    sample_quality(repo / "reports" / "quality" / "quality_report_20260501_010101.json")
    sample_errors(repo / "reports" / "errors" / "scan_error_report_20260501_010101.json")
    output = generate_summary_report(repo)
    text = output.read_text(encoding="utf-8")
    assert "小说库整理汇总报告" in text
    assert "重复检测汇总" in text
    assert "质量问题汇总" in text
    assert "扫描错误汇总" in text
    assert "建议下一步操作" in text
