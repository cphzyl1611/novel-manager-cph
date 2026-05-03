from novel_manager.chapter_parser import parse_chapters


def test_parse_arabic_chapter():
    result = parse_chapters("第1章 开始\n正文")
    assert len(result.chapters) == 1
    assert result.chapters[0]["chapter_no"] == 1


def test_parse_chinese_chapter():
    result = parse_chapters("第一章 开始\n正文")
    assert len(result.chapters) == 1
    assert result.chapters[0]["chapter_no"] == 1


def test_parse_prologue():
    result = parse_chapters("序章\n正文")
    assert len(result.chapters) == 1
    assert result.chapters[0]["chapter_type"] == "prologue"


def test_parse_english_chapter():
    result = parse_chapters("Chapter 1\nbody")
    assert len(result.chapters) == 1
    assert result.chapters[0]["chapter_no"] == 1


def test_parse_no_chapter_does_not_crash():
    result = parse_chapters("没有章节标题的正文")
    assert result.chapters == []
