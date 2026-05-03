from __future__ import annotations

import hashlib
import re
from pathlib import Path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


TITLE_NOISE = [
    "精校版",
    "全本",
    "完本",
    "最新章节",
    "无弹窗",
    "笔趣阁",
    "txt",
    "TXT",
    "作者：",
    "作者:",
]


def _normalize_basic(value: str | None) -> str:
    value = value or ""
    value = value.replace("\ufeff", "")
    value = re.sub(r"[\[\(（【].{0,30}?(?:www\.|http|小说网|笔趣阁|sxsy|来源).{0,30}?[\]\)）】]", " ", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_title(title: str | None) -> str:
    value = _normalize_basic(title)
    value = re.sub(r"^\[[^\]]+\]\s*", " ", value)
    value = re.sub(r"^【[^】]+】\s*", " ", value)
    value = re.sub(r"\.[Tt][Xx][Tt](?:\.[Tt][Xx][Tt])*$", "", value)
    value = re.sub(r"(作品)?作者\s*[:：]\s*.*$", " ", value)
    value = re.sub(r"[_\- ]*(?:P站正式版本|AI加料|加料|无减全本|全本|未完结|完结|连载|排版|修订|重置)", " ", value, flags=re.I)
    value = re.sub(r"\b\d+\s*[-_]\s*\d+\s*(?:章|卷)?(?:未完结|完结|连载)?", " ", value)
    value = re.sub(r"[（(]\s*\d+\s*[-_]\s*\d+\s*(?:章|卷)?\s*[）)]", " ", value)
    value = re.sub(r"[（(]\s*\d+\s*卷\s*\d+\s*章\s*[）)]", " ", value)
    value = re.sub(r"[（(]\s*\d+\s*[）)]", " ", value)
    value = re.sub(r"\d{2}[_-]\d{2}", " ", value)
    for noise in TITLE_NOISE:
        value = value.replace(noise, " ")
    value = re.sub(r"[_\-]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" -_《》[]【】()（）")
    return value.lower()


def normalize_author(author: str | None) -> str:
    value = _normalize_basic(author)
    value = re.sub(r"^(作者|作家)\s*[:：]\s*", "", value)
    return re.sub(r"\s+", "", value).lower()


def normalize_chapter_title(title: str | None) -> str:
    value = _normalize_basic(title)
    value = re.sub(r"\s+", "", value)
    return value.lower()
