from __future__ import annotations

from pathlib import Path

from charset_normalizer import from_bytes

FALLBACK_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "utf-16", "big5")
MOJIBAKE_THRESHOLD = 0.02


def read_text_safely(path: Path, max_bytes: int | None = None) -> dict:
    raw = path.read_bytes()
    source_size = len(raw)
    if max_bytes is not None and source_size > max_bytes:
        raw = raw[:max_bytes]

    text, encoding, confidence, warning = _detect_and_decode(raw)
    had_decode_error = confidence < 0.5 and not _contains_chinese(text)
    replacement_ratio = text.count("�") / max(len(text), 1)

    decode_warning = None
    if warning:
        decode_warning = warning
    elif replacement_ratio > MOJIBAKE_THRESHOLD:
        decode_warning = "文本包含较多替换字符，编码识别可能不准确"
    elif confidence < 0.7:
        decode_warning = "文本编码识别置信度较低，可能存在少量乱码"

    return {
        "text": text,
        "encoding": encoding,
        "confidence": round(confidence, 4),
        "had_decode_error": had_decode_error,
        "source_size": source_size,
        "decode_warning": decode_warning,
        "replacement_ratio": round(replacement_ratio, 4),
    }


def _detect_and_decode(raw: bytes) -> tuple[str, str, float, str | None]:
    # BOM detection
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig", 1.0, None
    if raw.startswith(b"\xff\xfe"):
        try:
            return raw.decode("utf-16-le"), "utf-16-le", 1.0, None
        except UnicodeDecodeError:
            pass
    if raw.startswith(b"\xfe\xff"):
        try:
            return raw.decode("utf-16-be"), "utf-16-be", 1.0, None
        except UnicodeDecodeError:
            pass

    # charset_normalizer
    matches = from_bytes(raw)
    best = matches.best()
    if best and best.encoding:
        confidence = float(best.percent_coherence or 0) / 100
        try:
            text = str(best)
            if _contains_chinese(text):
                return text, best.encoding, confidence, None
        except Exception:
            pass

    # Fallback: try encodings, pick the one with most Chinese chars
    best_text = ""
    best_enc = "utf-8"
    best_chinese = 0
    for enc in FALLBACK_ENCODINGS:
        try:
            text = raw.decode(enc)
            cc = _chinese_char_count(text)
            if cc > best_chinese:
                best_text = text
                best_enc = enc
                best_chinese = cc
        except UnicodeDecodeError:
            continue

    if best_text:
        return best_text, best_enc, 0.6, "使用了编码后备方案"

    # Last resort
    return raw.decode("utf-8", errors="replace"), "utf-8", 0.0, "无法确定编码，已使用替换字符"


def _chinese_char_count(text: str) -> int:
    return sum(1 for c in text if "一" <= c <= "鿿" or "㐀" <= c <= "䶿")


def _contains_chinese(text: str) -> bool:
    return _chinese_char_count(text) > 10
