from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .utils import file_ts, write_json


def _env() -> Environment:
    template_dir = Path(__file__).resolve().parent.parent / "templates"
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def _book_public(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "id",
        "current_path",
        "repo_area",
        "file_name",
        "file_size",
        "raw_sha256",
        "clean_sha256",
        "title_norm",
        "author_norm",
        "char_count_clean",
        "chapter_count",
        "mojibake_rate",
        "ad_line_count",
        "ad_line_rate",
        "duplicate_chapter_count",
        "missing_chapter_count",
        "chapter_order_error_count",
        "truncated_risk",
        "quality_score",
        "quality_level",
        "quality_reasons_json",
        "created_at",
    ]
    return {key: row.get(key) for key in keys}


def generate_duplicate_report(repo: Path, groups: list[dict[str, Any]]) -> tuple[Path, Path]:
    ts = file_ts()
    json_path = repo / "reports" / "duplicate" / f"duplicate_report_{ts}.json"
    html_path = repo / "reports" / "duplicate" / f"duplicate_report_{ts}.html"
    public_groups = []
    for group in groups:
        members = []
        for member in group["members"]:
            public_member = {key: value for key, value in member.items() if key != "book"}
            public_member["book"] = _book_public(member["book"])
            members.append(public_member)
        public_groups.append({**{k: v for k, v in group.items() if k != "members"}, "members": members})
    payload = {"generated_at": ts, "groups": public_groups}
    write_json(json_path, payload)
    html = _env().get_template("duplicate_report.html.j2").render(**payload)
    html_path.write_text(html, encoding="utf-8")
    return html_path, json_path


def generate_quality_report(conn: sqlite3.Connection, repo: Path, area: str) -> tuple[Path, Path]:
    ts = file_ts()
    json_path = repo / "reports" / "quality" / f"quality_report_{ts}.json"
    html_path = repo / "reports" / "quality" / f"quality_report_{ts}.html"
    if area == "all":
        rows = conn.execute("SELECT * FROM books WHERE status = 'active' ORDER BY quality_score ASC, id ASC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM books WHERE status = 'active' AND repo_area = ? ORDER BY quality_score ASC, id ASC",
            (area,),
        ).fetchall()
    books = []
    for row in rows:
        item = _book_public(dict(row))
        try:
            item["quality_reasons"] = json.loads(item.get("quality_reasons_json") or "[]")
        except json.JSONDecodeError:
            item["quality_reasons"] = []
        books.append(item)
    payload = {"generated_at": ts, "area": area, "books": books}
    write_json(json_path, payload)
    html_path.write_text(_env().get_template("quality_report.html.j2").render(**payload), encoding="utf-8")
    return html_path, json_path


def generate_error_report(conn: sqlite3.Connection, repo: Path) -> tuple[Path, Path]:
    ts = file_ts()
    json_path = repo / "reports" / "errors" / f"scan_error_report_{ts}.json"
    html_path = repo / "reports" / "errors" / f"scan_error_report_{ts}.html"
    rows = conn.execute("SELECT * FROM scan_errors ORDER BY id DESC").fetchall()
    errors = [dict(row) for row in rows]
    payload = {"generated_at": ts, "errors": errors}
    write_json(json_path, payload)
    html_path.write_text(_env().get_template("scan_error_report.html.j2").render(**payload), encoding="utf-8")
    return html_path, json_path
