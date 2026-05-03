import json
import sqlite3
import uuid
from pathlib import Path

from novel_manager.db import initialize, upsert_book
from novel_manager.rename_planner import (
    build_rename_plan,
    clean_title_for_filename,
    extract_author_from_filename,
    extract_statuses_from_filename_and_tags,
    generate_target_filename,
    sanitize_filename,
    validate_author,
    write_rename_plan_reports,
)
from novel_manager.report_index import generate_report_index
from novel_manager.summary_report import generate_summary_report


def repo() -> Path:
    root = Path(".tmp") / "rename_tests" / uuid.uuid4().hex
    for rel in ["library", "incoming", "archive", "reports/summary", "reports/rename", "logs"]:
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def conn():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    initialize(db)
    return db


def payload(path: Path, **overrides):
    path.write_text("content", encoding="utf-8")
    data = {
        "current_path": str(path),
        "original_path": str(path),
        "repo_area": path.parent.name,
        "file_name": path.name,
        "file_size": path.stat().st_size,
        "mtime": 1.0,
        "raw_sha256": "raw-" + path.name,
        "clean_sha256": "clean-" + path.name,
        "title_raw": path.stem,
        "title_norm": "",
        "author_raw": "",
        "author_norm": "",
        "encoding": "utf-8",
        "encoding_confidence": 1.0,
        "decode_status": "ok",
        "char_count_raw": 100,
        "char_count_clean": 100,
        "line_count_raw": 10,
        "line_count_clean": 10,
        "chapter_count": 2,
        "mojibake_rate": 0,
        "ad_line_count": 0,
        "ad_line_rate": 0,
        "duplicate_chapter_count": 0,
        "missing_chapter_count": 0,
        "chapter_order_error_count": 0,
        "truncated_risk": 0,
        "quality_score": 80,
        "quality_level": "good",
        "quality_reasons_json": "[]",
        "status": "active",
        "reading_status": None,
        "created_at": "2026-01-01 00:00:00",
        "updated_at": "2026-01-02 00:00:00",
    }
    data.update(overrides)
    return data


def add_book(db, root: Path, name: str, area="library", **overrides) -> int:
    return upsert_book(db, payload(root / area / name, **{"repo_area": area, **overrides}))


def target_for_name(name: str, **overrides) -> dict:
    book = {"file_name": name, "title_raw": name, "title_norm": "", "author_raw": "", "author_norm": "", **overrides}
    return generate_target_filename(book, style="title-author-status")


def test_sanitize_filename_rules():
    name, risks = sanitize_filename('CON<>:"/\\|?*.txt.txt')
    assert name == "CON_file.txt"
    assert "unsafe_chars_removed" in risks
    assert "windows_reserved_name" in risks
    empty, empty_risks = sanitize_filename("   ")
    assert empty == "untitled.txt"
    assert "title_missing" in empty_risks
    long, long_risks = sanitize_filename("a" * 200, max_length=20)
    assert long.endswith(".txt")
    assert len(long) <= 20
    assert "target_truncated" in long_risks


def test_author_validation_and_extraction():
    assert extract_author_from_filename("书名 作者：张三.txt") == "张三"
    assert extract_author_from_filename("书名_作品作者：李四.txt") == "李四"
    assert extract_author_from_filename("书名 [作者：王五].txt") == "王五"
    assert validate_author("txt下载 http www =====")["suspicious"] is True
    assert validate_author("这是一个非常非常非常非常非常非常长的作者名字")["suspicious"] is True
    assert validate_author("未知作者")["valid"] is False
    assert validate_author("unknown")["valid"] is False
    assert validate_author("会叫的火星.txt.txt")["author"] == "会叫的火星"


def test_status_extraction():
    assert extract_statuses_from_filename_and_tags({"file_name": "书名 全本 精校.txt"}, []) == ["完本", "精校"]
    assert extract_statuses_from_filename_and_tags({"file_name": "书名 未完结 加料.txt"}, []) == ["连载", "加料"]
    assert extract_statuses_from_filename_and_tags({"file_name": "书名 P站正式版本 AI加料.txt"}, []) == ["加料", "正式版"]


def test_required_filename_examples():
    cases = [
        ("[sxsy.org]《模拟器中的老婆们竟然成真了！》1-127未完结 作者： 会叫的火星.txt", {}, "模拟器中的老婆们竟然成真了！ - 会叫的火星 [连载].txt"),
        ("[sxsy.org]《穿越乱世：我靠胯下神鞭收尽天下美娇娘》（1-20章）作者：佚名 未完结.txt", {}, "穿越乱世：我靠胯下神鞭收尽天下美娇娘 - 佚名 [连载].txt"),
        ("[sxsy.org]催眠系统陪我穿回古代玩全家桶（1-98完结）.txt", {}, "催眠系统陪我穿回古代玩全家桶 [完本].txt"),
        ("高考陪读那三年 (2).txt", {}, "高考陪读那三年.txt"),
        ("高考陪读那三年 P站正式版本.txt", {}, "高考陪读那三年 [正式版].txt"),
        ("《邻居家的榨汁姬》排版01_30连载（05卷08章）_作品作者：刹那雪.txt", {}, "邻居家的榨汁姬 - 刹那雪 [连载].txt"),
        ("娱乐：魅魔表弟，力捧天仙母女1-440 AI加料.txt", {}, "娱乐：魅魔表弟，力捧天仙母女 [加料].txt"),
        ("红颜后宫录（无减全本）作者：骑着单车去旅行.txt", {}, "红颜后宫录 - 骑着单车去旅行 [完本].txt"),
        ("诸天恶魔系统（修订383）作者：未知.txt", {}, "诸天恶魔系统 - 未知 [修订].txt"),
        ("《全班地铁求生，只有我一个男生，多子多福》1-52未完结 作者： 会叫的火星.txt.txt", {}, "全班地铁求生，只有我一个男生，多子多福 - 会叫的火星 [连载].txt"),
        ("（NTL♥纯肉♥反派代入）《红颜堕之食寝病栋》（1-20.txt", {"author_norm": "为生活写黄"}, "红颜堕之食寝病栋 - 为生活写黄.txt"),
    ]
    for name, overrides, expected in cases:
        assert target_for_name(name, **overrides)["target_file_name"] == expected


def test_unknown_author_default_and_opt_in():
    book = {"file_name": "高考陪读那三年.txt", "title_raw": "高考陪读那三年", "title_norm": "", "author_raw": "", "author_norm": ""}
    assert generate_target_filename(book, style="title-author-status")["target_file_name"] == "高考陪读那三年.txt"
    assert generate_target_filename(book, style="title-author-status", include_unknown_author=True)["target_file_name"] == "高考陪读那三年 - 未知作者.txt"
    book["author_norm"] = "未知作者"
    assert generate_target_filename(book, style="title-author-status")["target_file_name"] == "高考陪读那三年.txt"
    assert "author_missing" in generate_target_filename(book, style="title-author-status")["risk_flags"]
    assert generate_target_filename(book, style="title-author-status", include_unknown_author=True)["target_file_name"] == "高考陪读那三年 - 未知作者.txt"


def test_unknown_author_examples_and_author_txt_suffix():
    no_author = {"file_name": "[sxsy.org]催眠系统陪我穿回古代玩全家桶（1-98完结）.txt", "title_raw": "", "title_norm": "", "author_raw": "", "author_norm": ""}
    assert generate_target_filename(no_author, style="title-author-status")["target_file_name"] == "催眠系统陪我穿回古代玩全家桶 [完本].txt"
    assert generate_target_filename(no_author, style="title-author-status", include_unknown_author=True)["target_file_name"] == "催眠系统陪我穿回古代玩全家桶 - 未知作者 [完本].txt"
    plain = {"file_name": "三个婊子老婆的饲养日记.txt", "title_raw": "", "title_norm": "", "author_raw": "", "author_norm": ""}
    assert generate_target_filename(plain, style="title-author-status")["target_file_name"] == "三个婊子老婆的饲养日记.txt"
    assert generate_target_filename(plain, style="title-author-status", include_unknown_author=True)["target_file_name"] == "三个婊子老婆的饲养日记 - 未知作者.txt"
    with_suffix = {"file_name": "《全班地铁求生，只有我一个男生，多子多福》1-52未完结 作者： 会叫的火星.txt.txt", "title_raw": "", "title_norm": "", "author_raw": "会叫的火星.txt", "author_norm": ""}
    assert generate_target_filename(with_suffix, style="title-author-status")["target_file_name"] == "全班地铁求生，只有我一个男生，多子多福 - 会叫的火星 [连载].txt"
    explicit_unknown = {"file_name": "诸天恶魔系统（修订383）作者：未知.txt", "title_raw": "", "title_norm": "", "author_raw": "", "author_norm": ""}
    assert generate_target_filename(explicit_unknown, style="title-author-status")["target_file_name"] == "诸天恶魔系统 - 未知 [修订].txt"


def test_clean_title_noise_metadata():
    cleaned = clean_title_for_filename("[sxsy.org]《模拟器中的老婆们竟然成真了！》1-127未完结 作者： 会叫的火星.txt")
    assert cleaned["title_cleaned"] == "模拟器中的老婆们竟然成真了！"
    assert "source_prefix" in cleaned["removed_noise"]
    assert "source_prefix_removed" in cleaned["risk_flags"]


def test_build_rename_plan_risks_conflicts_and_filters():
    root = repo()
    with conn() as db:
        add_book(db, root, "同名 (2).txt", title_norm="同名", author_norm="作者")
        add_book(db, root, "同名 (3).txt", title_norm="同名", author_norm="作者")
        add_book(db, root, "low.txt", title_norm="低质", author_norm="作者", quality_score=50)
        add_book(db, root, "moji.txt", title_norm="乱码", author_norm="作者", mojibake_rate=0.01)
        add_book(db, root, "same - 作者.txt", title_norm="same", author_norm="作者")
        plan = build_rename_plan(db, root, include_unchanged=False, style="title-author")
    assert plan["stats"]["target_name_conflict"] >= 2
    assert plan["stats"]["low_quality_book"] == 1
    assert any("mojibake_risk" in item["risk_flags"] for item in plan["suggestions"])
    assert all(item["action"] != "no_change" for item in plan["suggestions"])
    conflict = next(item for item in plan["suggestions"] if "target_name_conflict" in item["risk_flags"])
    assert conflict["conflict_with"]
    assert "冲突" in conflict["reason_summary"]


def test_reports_summary_and_index():
    root = repo()
    with conn() as db:
        add_book(db, root, "高考陪读那三年.txt", title_norm="高考陪读那三年", author_norm="")
        plan = build_rename_plan(db, root, query="高考陪读", include_unchanged=True)
        html, js, md = write_rename_plan_reports(root, plan)
    assert html.exists() and js.exists() and md.exists()
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["suggestions"]
    assert (root / "library" / "高考陪读那三年.txt").exists()
    summary = generate_summary_report(root).read_text(encoding="utf-8")
    assert "重命名建议汇总" in summary
    index_html, index_md = generate_report_index(root)
    assert "rename" in index_html.read_text(encoding="utf-8")
    assert "rename" in index_md.read_text(encoding="utf-8")
