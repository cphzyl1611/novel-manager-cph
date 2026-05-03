from __future__ import annotations

from dataclasses import dataclass

from .config import DEFAULT_CLEANING_RULES


@dataclass
class CleanMetrics:
    ad_line_count: int
    ad_line_rate: float
    mojibake_rate: float
    char_count_raw: int
    char_count_clean: int
    line_count_raw: int
    line_count_clean: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "ad_line_count": self.ad_line_count,
            "ad_line_rate": self.ad_line_rate,
            "mojibake_rate": self.mojibake_rate,
            "char_count_raw": self.char_count_raw,
            "char_count_clean": self.char_count_clean,
            "line_count_raw": self.line_count_raw,
            "line_count_clean": self.line_count_clean,
        }


def mojibake_rate(text: str) -> float:
    if not text:
        return 0.0
    suspicious = "�锟斤拷ÃÂ¤¦§©ª«¬®¯¼½¾¿"
    count = sum(1 for ch in text if ch in suspicious)
    count += text.count("????")
    return min(1.0, count / max(1, len(text)))


def clean_text(text: str, ad_keywords: list[str] | None = None) -> tuple[str, CleanMetrics]:
    keywords = ad_keywords or DEFAULT_CLEANING_RULES["ad_keywords"]
    raw = text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
    raw = raw.replace("\u3000", " ")
    raw_lines = raw.split("\n")
    cleaned_lines: list[str] = []
    ad_count = 0
    blank_seen = False
    for line in raw_lines:
        stripped = line.strip()
        is_ad = any(keyword.lower() in stripped.lower() for keyword in keywords)
        if is_ad:
            ad_count += 1
            continue
        if stripped == "":
            if blank_seen:
                continue
            blank_seen = True
            cleaned_lines.append("")
            continue
        blank_seen = False
        cleaned_lines.append(stripped)
    cleaned = "\n".join(cleaned_lines).strip()
    clean_lines = cleaned.split("\n") if cleaned else []
    metrics = CleanMetrics(
        ad_line_count=ad_count,
        ad_line_rate=ad_count / max(1, len(raw_lines)),
        mojibake_rate=mojibake_rate(raw),
        char_count_raw=len(raw),
        char_count_clean=len(cleaned),
        line_count_raw=len(raw_lines),
        line_count_clean=len(clean_lines),
    )
    return cleaned, metrics
