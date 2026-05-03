from novel_manager.quality import score_quality


def base_score(**overrides):
    data = dict(
        char_count_clean=50000,
        chapter_count=30,
        mojibake_rate=0.0,
        ad_line_count=0,
        ad_line_rate=0.0,
        duplicate_chapter_count=0,
        missing_chapter_count=0,
        chapter_order_error_count=0,
        file_name="A.txt",
        title_norm="a",
        author_norm="author",
    )
    data.update(overrides)
    return score_quality(**data)


def test_quality_returns_score():
    result = base_score()
    assert 0 <= result.quality_score <= 100
    assert result.quality_level in {"excellent", "good", "normal", "poor"}


def test_many_ads_reduce_score():
    clean = base_score()
    dirty = base_score(ad_line_count=100, ad_line_rate=0.2)
    assert dirty.quality_score < clean.quality_score


def test_mojibake_reduces_score():
    clean = base_score()
    bad = base_score(mojibake_rate=0.1)
    assert bad.quality_score < clean.quality_score
