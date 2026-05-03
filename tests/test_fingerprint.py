from novel_manager.fingerprint import normalize_title, sha256_text


def test_sha256_text_same_content_is_same():
    assert sha256_text("abc") == sha256_text("abc")


def test_normalize_title_removes_noise():
    normalized = normalize_title("《某书》精校版 笔趣阁 txt")
    assert "精校版" not in normalized
    assert "笔趣阁" not in normalized
    assert "txt" not in normalized
    assert "某书" in normalized


def test_normalize_title_stage2_noise_rules():
    assert normalize_title("高考陪读那三年 P站正式版本.txt") == "高考陪读那三年"
    assert normalize_title("高考陪读那三年 (2).txt") == "高考陪读那三年"
    assert normalize_title("[sxsy.org]《模拟器中的老婆们竟然成真了！》1-127未完结 作者：会叫的火星.txt") == "模拟器中的老婆们竟然成真了！"
    assert normalize_title("《邻居家的榨汁姬》排版01_30连载（05卷08章）_作品作者：刹那雪.txt") == "邻居家的榨汁姬"
