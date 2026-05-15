#!/usr/bin/env python3
"""Web/PWA smoke test — read-only checks against a running server.

Usage:
    python scripts/smoke_web_pwa.py --base-url http://127.0.0.1:8765 --repo "D:/NovelRepo_Test"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "novel_manager" / "server" / "static"
REPORTS_DIR = PROJECT_ROOT / "reports" / "smoke"


class SmokeChecker:
    def __init__(self, base_url: str, repo_path: str):
        self.base_url = base_url.rstrip("/")
        self.repo_path = repo_path
        self.failures: list[str] = []
        self.passes: list[str] = []
        self.warnings: list[str] = []

    def _check(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.passes.append(name)
        else:
            self.failures.append(f"{name}: {detail}" if detail else name)
        return condition

    def _warn(self, msg: str) -> None:
        self.warnings.append(msg)

    # ---- API checks ----

    def check_api_health(self) -> None:
        try:
            r = requests.get(f"{self.base_url}/api/health", timeout=10)
            self._check("GET /api/health 200", r.status_code == 200, f"status={r.status_code}")
            if r.status_code == 200:
                data = r.json()
                self._check("health.ok is True", data.get("ok") is True)
        except requests.RequestException as e:
            self._check("GET /api/health", False, str(e))

    def check_api_books(self) -> None:
        try:
            r = requests.get(
                f"{self.base_url}/api/books?page=1&page_size=35&sort=recent_read",
                timeout=10,
            )
            self._check("GET /api/books 200", r.status_code == 200, f"status={r.status_code}")
            if r.status_code != 200:
                return
            data = r.json()
            items = data.get("items", [])
            pagination = data.get("pagination", {})

            self._check("books has pagination", bool(pagination))
            self._check("books has total", isinstance(data.get("total"), int))
            if pagination:
                for key in ("page", "page_size", "total", "total_pages"):
                    self._check(f"pagination.{key} present", key in pagination)

            for item in items:
                bid = item.get("book_id", "?")
                area = item.get("area", "")
                if area != "library":
                    self._check(f"book {bid} area is library", False, f"area={area}")
                current_path = item.get("current_path")
                if current_path:
                    if not Path(current_path).exists():
                        self._check(f"book {bid} path exists", False, str(current_path))

            self._check("all items area=library", all(i.get("area") == "library" for i in items))
        except requests.RequestException as e:
            self._check("GET /api/books", False, str(e))

    def check_api_sync(self) -> None:
        try:
            r = requests.get(f"{self.base_url}/api/sync/manifest", timeout=10)
            self._check("GET /api/sync/manifest 200", r.status_code == 200, f"status={r.status_code}")
            if r.status_code == 200:
                data = r.json()
                for key in ("repo_id", "server_revision", "library_stats"):
                    self._check(f"manifest.{key} present", key in data)
        except requests.RequestException as e:
            self._check("GET /api/sync/manifest", False, str(e))

    def check_api_health_summary(self) -> None:
        try:
            r = requests.get(f"{self.base_url}/api/health/summary", timeout=10)
            self._check("GET /api/health/summary 200", r.status_code == 200, f"status={r.status_code}")
            if r.status_code == 200:
                data = r.json()
                integrity = data.get("integrity", {})
                self._check("integrity.missing_files=0", integrity.get("missing_files", 0) == 0)
                self._check("ignored_missing_files_count present", "ignored_missing_files_count" in integrity)
        except requests.RequestException as e:
            self._check("GET /api/health/summary", False, str(e))

    def check_api_health_issues(self) -> None:
        try:
            r = requests.get(f"{self.base_url}/api/health/issues", timeout=10)
            self._check("GET /api/health/issues 200", r.status_code == 200, f"status={r.status_code}")
            if r.status_code == 200:
                data = r.json()
                items = data.get("items", [])
                missing = [i for i in items if i.get("code") == "missing_file"]
                self._check("no missing_file in issues", len(missing) == 0, f"found {len(missing)}")
                known = [i for i in items if i.get("code") == "known_missing"]
                self._check("no known_missing in issues", len(known) == 0, f"found {len(known)}")
        except requests.RequestException as e:
            self._check("GET /api/health/issues", False, str(e))

    # ---- Static file checks ----

    def check_static_files(self) -> None:
        app_js = STATIC_DIR / "app.js"
        index_html = STATIC_DIR / "index.html"
        sw_js = STATIC_DIR / "service-worker.js"

        if app_js.exists():
            content = app_js.read_text(encoding="utf-8")
            self._check("app.js exists", True)
            self._check("app.js has version header", "offlinecache1" in content[:100])
            self._check("app.js no onclick goToPage", 'onclick="goToPage' not in content)
            self._check("app.js has safeNumber", "function safeNumber" in content)
            self._check("app.js has buildProgressPayload", "function buildProgressPayload" in content)
            self._check("app.js has data-action page-prev", 'data-action="page-prev"' in content)
            self._check("app.js uses sort=recent_read", "sort=recent_read" in content)
            self._check("app.js has NovelHubCache IDB", "NovelHubCache" in content)
            self._check("app.js has offline mode", "offlineState" in content)
            self._check("app.js has cacheBooksSnapshot", "cacheBooksSnapshot" in content)
            self._check("app.js has cacheBookContent", "cacheBookContent" in content)
            self._check("app.js has pending_progress store", "pending_progress" in content)
            self._check("app.js no pending_replace", "pending_replace" not in content)
            self._check("app.js no pending_delete", "pending_delete" not in content)
            self._check("app.js no pending_upload_file", "pending_upload_file" not in content)
        else:
            self._check("app.js exists", False)

        if index_html.exists():
            content = index_html.read_text(encoding="utf-8")
            self._check("index.html exists", True)
            self._check('index.html has shelfPagination', 'id="shelfPagination"' in content)
            self._check("index.html uses offlinecache1", 'offlinecache1' in content)
        else:
            self._check("index.html exists", False)

        if sw_js.exists():
            content = sw_js.read_text(encoding="utf-8")
            self._check("service-worker.js exists", True)
            self._check("sw.js has CACHE_NAME", "CACHE_NAME" in content)
            self._check("sw.js has offlinecache1", "offlinecache1" in content)
            self._check("sw.js does not cache POST", "request.method !== 'GET'" in content)
        else:
            self._check("service-worker.js exists", False)

    # ---- Report ----

    def run_all(self) -> dict:
        self.check_api_health()
        self.check_api_books()
        self.check_api_sync()
        self.check_api_health_summary()
        self.check_api_health_issues()
        self.check_static_files()
        return self._build_report()

    def _build_report(self) -> dict:
        total = len(self.passes) + len(self.failures)
        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "base_url": self.base_url,
            "repo_path": self.repo_path,
            "summary": {
                "total": total,
                "passed": len(self.passes),
                "failed": len(self.failures),
                "warnings": len(self.warnings),
            },
            "passes": self.passes,
            "failures": self.failures,
            "warnings": self.warnings,
        }

    def save_report(self, report: dict) -> tuple[Path, Path]:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        md_path = REPORTS_DIR / f"smoke_web_pwa_{ts}.md"
        md_lines = [
            f"# Smoke Test Report — {report['timestamp']}",
            "",
            f"**Base URL:** {report['base_url']}",
            f"**Repo:** {report['repo_path']}",
            "",
            f"## Summary: {report['summary']['passed']}/{report['summary']['total']} passed",
            "",
        ]
        if report["failures"]:
            md_lines.append("## Failures")
            for f in report["failures"]:
                md_lines.append(f"- FAIL: {f}")
            md_lines.append("")
        md_lines.append("## All Checks")
        for p in report["passes"]:
            md_lines.append(f"- PASS: {p}")
        for f in report["failures"]:
            md_lines.append(f"- FAIL: {f}")
        md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

        json_path = REPORTS_DIR / f"smoke_web_pwa_{ts}.json"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        return md_path, json_path


def main():
    parser = argparse.ArgumentParser(description="Web/PWA smoke test (read-only)")
    parser.add_argument("--base-url", required=True, help="Server base URL")
    parser.add_argument("--repo", required=True, help="Repository path")
    args = parser.parse_args()

    checker = SmokeChecker(args.base_url, args.repo)
    report = checker.run_all()
    md_path, json_path = checker.save_report(report)

    print(f"Passed: {report['summary']['passed']}/{report['summary']['total']}")
    if report["failures"]:
        print(f"Failures: {len(report['failures'])}")
        for f in report["failures"]:
            print(f"  FAIL {f}")
    print(f"Report: {md_path}")
    print(f"Report: {json_path}")

    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
