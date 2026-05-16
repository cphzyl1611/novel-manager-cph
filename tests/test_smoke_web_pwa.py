"""Tests for Web/PWA smoke checker — static checks only, no server needed."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.smoke_web_pwa import SmokeChecker


def test_can_instantiate():
    checker = SmokeChecker("http://127.0.0.1:8765", "/fake/repo")
    assert checker.base_url == "http://127.0.0.1:8765"


def test_check_method_records_pass_and_fail():
    checker = SmokeChecker("http://127.0.0.1:8765", "/fake/repo")
    assert checker._check("passing", True)
    assert len(checker.passes) == 1
    assert not checker._check("failing", False, "detail")
    assert len(checker.failures) == 1


def test_static_checks_app_js_version():
    checker = SmokeChecker("http://127.0.0.1:8765", "/fake/repo")
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "app.js").write_text(
            '// NovelHub app.js syncui1\nconsole.log("[NovelHub] app.js syncui1 loaded");\n'
            'function safeNumber(v,fallback){var n=Number(v);return Number.isFinite(n)?n:fallback}\n'
            'function buildProgressPayload(pd){return{}}\n'
            ';h+=\'<button class="page-btn" data-action="page-prev">\';',
            encoding="utf-8",
        )
        import scripts.smoke_web_pwa as mod
        orig = mod.STATIC_DIR
        mod.STATIC_DIR = Path(td)
        checker.check_static_files()
        mod.STATIC_DIR = orig
        assert "app.js has version header" in checker.passes
        assert "app.js has safeNumber" in checker.passes
        assert "app.js has buildProgressPayload" in checker.passes
        assert "app.js has data-action page-prev" in checker.passes


def test_static_checks_rejects_onclick_goto_page():
    checker = SmokeChecker("http://127.0.0.1:8765", "/fake/repo")
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "app.js").write_text(
            '// NovelHub app.js syncui1\nconsole.log("[NovelHub] app.js syncui1 loaded");\n'
            '<button onclick="goToPage(2)">Next Page</button>\n',
            encoding="utf-8",
        )
        import scripts.smoke_web_pwa as mod
        orig = mod.STATIC_DIR
        mod.STATIC_DIR = Path(td)
        checker.check_static_files()
        mod.STATIC_DIR = orig
        assert "app.js no onclick goToPage" in checker.failures


def test_static_checks_index_html_shelf_pagination():
    checker = SmokeChecker("http://127.0.0.1:8765", "/fake/repo")
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "index.html").write_text(
            '<!DOCTYPE html>\n<div id="shelfPagination" class="pagination-dock hidden"></div>\n'
            '<script src="app.js?v=syncui1"></script>\n'
        )
        import scripts.smoke_web_pwa as mod
        orig = mod.STATIC_DIR
        mod.STATIC_DIR = Path(td)
        checker.check_static_files()
        mod.STATIC_DIR = orig
        assert 'index.html has shelfPagination' in checker.passes


def test_static_checks_service_worker():
    checker = SmokeChecker("http://127.0.0.1:8765", "/fake/repo")
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "service-worker.js").write_text("const CACHE_NAME = 'novelhub-syncui1';\n")
        import scripts.smoke_web_pwa as mod
        orig = mod.STATIC_DIR
        mod.STATIC_DIR = Path(td)
        checker.check_static_files()
        mod.STATIC_DIR = orig
        assert "sw.js has CACHE_NAME" in checker.passes


def test_report_builds_correct_summary():
    checker = SmokeChecker("http://127.0.0.1:8765", "/fake/repo")
    checker._check("t1", True)
    checker._check("t2", False, "oops")
    report = checker._build_report()
    assert report["summary"]["total"] == 2
    assert report["summary"]["passed"] == 1
    assert report["summary"]["failed"] == 1


def test_report_saves_markdown_and_json():
    checker = SmokeChecker("http://127.0.0.1:8765", "/fake/repo")
    checker._check("test ok", True)
    report = checker._build_report()
    md_path, json_path = checker.save_report(report)
    assert md_path.exists() and md_path.suffix == ".md"
    assert json_path.exists() and json_path.suffix == ".json"
    assert "test ok" in md_path.read_text(encoding="utf-8")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["summary"]["passed"] == 1
    md_path.unlink()
    json_path.unlink()


def test_smoke_checker_is_read_only():
    checker = SmokeChecker("http://127.0.0.1:8765", "/fake/repo")
    public = [m for m in dir(checker) if not m.startswith("_")]
    assert "delete" not in public
    assert "move" not in public
    assert "post" not in public
    assert "put" not in public
