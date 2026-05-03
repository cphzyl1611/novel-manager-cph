from novel_manager.text_cleaner import clean_text


def test_cleaner_removes_bom_and_normalizes_newlines():
    cleaned, metrics = clean_text("\ufeff第一行\r\n\r\n\r\n第二行")
    assert cleaned == "第一行\n\n第二行"
    assert metrics.line_count_raw == 4


def test_cleaner_counts_ad_lines():
    cleaned, metrics = clean_text("正文\n请收藏本站\n第二章")
    assert "请收藏本站" not in cleaned
    assert metrics.ad_line_count == 1


def test_cleaner_does_not_empty_normal_body():
    cleaned, _ = clean_text("这是正常正文。\n人物正在对话。")
    assert "正常正文" in cleaned
    assert len(cleaned) > 5
