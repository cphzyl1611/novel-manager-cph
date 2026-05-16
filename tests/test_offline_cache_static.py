"""Static checks for offline cache v1 — no server needed."""
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).parent.parent / "novel_manager" / "server" / "static"


def _read(path: str) -> str:
    return (STATIC / path).read_text(encoding="utf-8")


def test_app_js_syncui1_header():
    assert "syncui1" in _read("app.js")[:100]


def test_app_js_has_novel_hub_cache_idb():
    assert "NovelHubCache" in _read("app.js")


def test_app_js_has_books_store():
    content = _read("app.js")
    assert "createObjectStore('books'" in content or 'createObjectStore("books"' in content


def test_app_js_has_contents_store():
    content = _read("app.js")
    assert "createObjectStore('contents'" in content or 'createObjectStore("contents"' in content


def test_app_js_has_pending_progress_store():
    content = _read("app.js")
    assert "createObjectStore('pending_progress'" in content or 'createObjectStore("pending_progress"' in content


def test_app_js_has_offline_state():
    assert "offlineState" in _read("app.js")


def test_app_js_has_cache_books_snapshot():
    assert "cacheBooksSnapshot" in _read("app.js")


def test_app_js_has_cache_book_content():
    assert "cacheBookContent" in _read("app.js")


def test_app_js_no_dangerous_offline_queue():
    content = _read("app.js")
    assert "pending_replace" not in content
    assert "pending_delete" not in content
    assert "pending_upload_file" not in content


def test_app_js_has_disable_dangerous_ops():
    assert "disableDangerousOps" in _read("app.js")


def test_app_js_has_upload_pending_progress():
    assert "uploadPendingProgress" in _read("app.js")


def test_service_worker_syncui1():
    assert "syncui1" in _read("service-worker.js")


def test_service_worker_no_post_cache():
    assert "request.method !== 'GET'" in _read("service-worker.js")


def test_index_html_syncui1():
    assert "syncui1" in _read("index.html")
