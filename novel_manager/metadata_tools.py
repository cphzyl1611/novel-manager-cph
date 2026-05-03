from __future__ import annotations

import html
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .fingerprint import normalize_author, normalize_title
from .operations import log_operation
from .rename_planner import clean_title_for_filename, extract_author_from_filename, validate_author
from .utils import file_ts, now_ts, write_json

AREAS = {"library", "incoming", "archive", "review_duplicates", "all"}
DIRTY_FILE_PATTERNS = [
    "[sxsy.org]",
    ".txt.txt",
    "作者：",
    "作品作者：",
    "1-500",
    "1-127未完结",
    "P站正式版本",
]
DIRTY_TITLE_PATTERNS = ["sxsy", "txt", "作者", "P站正式版本", "(2)", "(3)"]


def _book_rows(
    conn: sqlite3.Connection,
    *,
    area: str = "library",
    query: str | None = None,
    book_id: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    if area != "all":
        clauses.append("repo_area = ?")
        params.append(area)
    if book_id is not None:
        clauses.append("id = ?")
        params.append(book_id)
    if query:
        like = f"%{query}%"
        clauses.append(
            "(COALESCE(file_name, '') LIKE ? OR COALESCE(current_path, '') LIKE ? "
            "OR COALESCE(title_raw, '') LIKE ? OR COALESCE(title_norm, '') LIKE ?)"
        )
        params.extend([like, like, like, like])
    sql = f"SELECT * FROM books WHERE {' AND '.join(f'({c})' for c in clauses)} ORDER BY id"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _strip_status(text: str) -> str:
    return re.sub(r"\s*[\[\(（【](?:完本|全本|完结|连载|未完结|精校|修订|加料|正式版)(?:\s+(?:完本|连载|精校|修订|加料|正式版))*[\]\)）】]\s*$", "", text).strip()


def _metadata_from_file_name(file_name: str, existing_author: str | None = None) -> dict[str, str]:
    stem = re.sub(r"(?i)(?:\.txt)+$", "", file_name).strip()
    stem = _strip_status(stem)
    author = ""
    explicit = extract_author_from_filename(file_name)
    explicit_valid = validate_author(explicit)
    if explicit_valid.get("valid"):
        author = str(explicit_valid["author"])
    if not author and " - " in stem:
        possible_title, possible_author = stem.rsplit(" - ", 1)
        possible_author = _strip_status(possible_author)
        valid = validate_author(possible_author)
        if valid.get("valid"):
            author = str(valid["author"])
            stem = possible_title
    if not author:
        valid_existing = validate_author(existing_author)
        if valid_existing.get("valid"):
            author = str(valid_existing["author"])
    title_info = clean_title_for_filename(stem)
    title = str(title_info.get("title_cleaned") or "").strip()
    if not title:
        title = re.sub(r"(?i)(?:\.txt)+$", "", file_name).strip()
    return {
        "file_name": file_name,
        "title_raw": title,
        "title_norm": normalize_title(title),
        "author_raw": author,
        "author_norm": normalize_author(author),
    }


def _diff(book: dict[str, Any], new_values: dict[str, str]) -> dict[str, dict[str, str]]:
    changes: dict[str, dict[str, str]] = {}
    for field, new_value in new_values.items():
        old_value = "" if book.get(field) is None else str(book.get(field))
        if old_value != new_value:
            changes[field] = {"old": old_value, "new": new_value}
    return changes


def refresh_metadata(
    conn: sqlite3.Connection,
    repo: Path,
    *,
    area: str = "library",
    query: str | None = None,
    book_id: int | None = None,
    dry_run: bool = False,
    apply: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    if area not in AREAS:
        raise ValueError(f"unsupported area: {area}")
    if dry_run and apply:
        raise ValueError("--dry-run and --apply cannot be used together")
    if not dry_run and not apply:
        raise ValueError("use --dry-run or --apply")

    rows = _book_rows(conn, area=area, query=query, book_id=book_id, limit=limit)
    items: list[dict[str, Any]] = []
    changed = 0
    updated = 0
    no_change = 0
    skipped = 0
    for book in rows:
        path = Path(str(book.get("current_path") or ""))
        item = {
            "book_id": book.get("id"),
            "current_path": str(path),
            "old_file_name": book.get("file_name"),
            "new_file_name": path.name,
            "old_title_norm": book.get("title_norm"),
            "new_title_norm": None,
            "status": "",
            "changes": {},
        }
        if not path.exists():
            item.update({"status": "skipped", "skip_reason": "current_path does not exist"})
            skipped += 1
            items.append(item)
            continue
        new_values = _metadata_from_file_name(path.name, book.get("author_raw") or book.get("author_norm"))
        changes = _diff(book, new_values)
        item["new_title_norm"] = new_values["title_norm"]
        item["changes"] = changes
        if not changes:
            item["status"] = "no_change"
            no_change += 1
            items.append(item)
            continue
        changed += 1
        if dry_run:
            item["status"] = "dry_run"
            items.append(item)
            continue
        now = now_ts()
        conn.execute(
            """
            UPDATE books
            SET file_name = ?, title_raw = ?, title_norm = ?, author_raw = ?, author_norm = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_values["file_name"],
                new_values["title_raw"],
                new_values["title_norm"],
                new_values["author_raw"],
                new_values["author_norm"],
                now,
                book["id"],
            ),
        )
        log_operation(
            conn,
            repo,
            operation_type="refresh_metadata",
            book_id=int(book["id"]),
            source_path=str(path),
            target_path=str(path),
            raw_sha256_before=book.get("raw_sha256"),
            raw_sha256_after=book.get("raw_sha256"),
            status="success",
            report_path=None,
            reason=f"refresh metadata: {book.get('title_norm') or ''} -> {new_values['title_norm']}",
        )
        item["status"] = "updated"
        updated += 1
        items.append(item)
    if apply:
        conn.commit()
    return {
        "dry_run": dry_run,
        "apply": apply,
        "total": len(rows),
        "change_count": changed,
        "updated_count": updated,
        "no_change_count": no_change,
        "skipped_count": skipped,
        "items": items,
    }


def _add_issue(issues: list[dict[str, Any]], severity: str, code: str, message: str, book: dict[str, Any] | None = None) -> None:
    issues.append(
        {
            "severity": severity,
            "code": code,
            "message": message,
            "book_id": book.get("id") if book else None,
            "file_name": book.get("file_name") if book else None,
            "current_path": book.get("current_path") if book else None,
        }
    )


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def _dirty_file_name(value: str) -> bool:
    return any(pattern in value for pattern in DIRTY_FILE_PATTERNS)


def _dirty_title(value: str) -> bool:
    return any(pattern.lower() in value.lower() for pattern in DIRTY_TITLE_PATTERNS)


def post_rename_check(conn: sqlite3.Connection, repo: Path) -> dict[str, Any]:
    rows = [dict(row) for row in conn.execute("SELECT * FROM books ORDER BY id").fetchall()]
    issues: list[dict[str, Any]] = []
    ok: list[dict[str, Any]] = []
    area_dirs = {
        "library": repo / "library",
        "incoming": repo / "incoming",
        "review_duplicates": repo / "review_duplicates",
    }
    for book in rows:
        path = Path(str(book.get("current_path") or ""))
        book_ok: list[str] = []
        if not path.exists():
            _add_issue(issues, "error", "missing_file", "books.current_path does not exist", book)
        else:
            book_ok.append("current_path exists")
        if book.get("file_name") != path.name:
            _add_issue(issues, "warning", "metadata_mismatch", "books.file_name does not match Path(current_path).name", book)
        else:
            book_ok.append("file_name matches current_path")
        if _dirty_file_name(path.name):
            _add_issue(issues, "warning", "dirty_file_name", "current_path still contains filename noise", book)
        if _dirty_title(str(book.get("title_norm") or "")):
            _add_issue(issues, "warning", "dirty_title_norm", "title_norm still contains noise", book)
        area = str(book.get("repo_area") or "")
        if area in area_dirs and not _inside(path, area_dirs[area]):
            _add_issue(issues, "warning", "repo_area_path_mismatch", f"repo_area={area} does not match current_path", book)
        if not book.get("raw_sha256"):
            _add_issue(issues, "warning", "missing_raw_sha256", "raw_sha256 is empty", book)
        if not book.get("clean_sha256"):
            _add_issue(issues, "warning", "missing_clean_sha256", "clean_sha256 is empty", book)
        if book_ok:
            ok.append({"book_id": book.get("id"), "checks": book_ok})

    try:
        for row in conn.execute("SELECT id, primary_book_id FROM work_groups WHERE primary_book_id IS NOT NULL").fetchall():
            exists = conn.execute("SELECT 1 FROM books WHERE id = ?", (row["primary_book_id"],)).fetchone()
            if not exists:
                _add_issue(issues, "error", "missing_primary_book", f"work_group {row['id']} primary_book_id does not exist")
        for row in conn.execute("SELECT id, book_id, work_group_id FROM book_group_members").fetchall():
            exists = conn.execute("SELECT 1 FROM books WHERE id = ?", (row["book_id"],)).fetchone()
            if not exists:
                _add_issue(issues, "error", "missing_group_member_book", f"book_group_member {row['id']} book_id does not exist")
    except sqlite3.Error:
        pass

    stats = {
        "ok_count": len(ok),
        "error_count": sum(1 for issue in issues if issue["severity"] == "error"),
        "warning_count": sum(1 for issue in issues if issue["severity"] == "warning"),
        "missing_file_count": sum(1 for issue in issues if issue["code"] == "missing_file"),
        "dirty_file_name_count": sum(1 for issue in issues if issue["code"] == "dirty_file_name"),
        "dirty_title_norm_count": sum(1 for issue in issues if issue["code"] == "dirty_title_norm"),
        "metadata_mismatch_count": sum(1 for issue in issues if issue["code"] == "metadata_mismatch"),
    }
    return {"generated_at": file_ts(), "repo": str(repo), "stats": stats, "ok": ok, "issues": issues}


def _html_report(payload: dict[str, Any]) -> str:
    rows = []
    for issue in payload["issues"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(issue['severity'])}</td><td>{html.escape(issue['code'])}</td>"
            f"<td>{html.escape(str(issue.get('book_id') or ''))}</td><td>{html.escape(str(issue.get('file_name') or ''))}</td>"
            f"<td><code>{html.escape(str(issue.get('current_path') or ''))}</code></td><td>{html.escape(issue['message'])}</td>"
            "</tr>"
        )
    issue_rows = "".join(rows) or "<tr><td colspan='6'>No issues</td></tr>"
    stats = payload["stats"]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Post Rename Check</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #202124; }}
    table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
    th, td {{ border-bottom: 1px solid #eee; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f6f8fa; }}
    code {{ word-break: break-all; }}
  </style>
</head>
<body>
  <h1>Post Rename Check</h1>
  <p>本报告只检查数据库和文件系统一致性，不修改文件。</p>
  <ul>
    <li>errors: {stats['error_count']}</li>
    <li>warnings: {stats['warning_count']}</li>
    <li>missing files: {stats['missing_file_count']}</li>
    <li>dirty file names: {stats['dirty_file_name_count']}</li>
    <li>dirty title_norm: {stats['dirty_title_norm_count']}</li>
    <li>metadata mismatch: {stats['metadata_mismatch_count']}</li>
  </ul>
  <h2>Issues</h2>
  <table><thead><tr><th>Severity</th><th>Code</th><th>Book ID</th><th>File</th><th>Path</th><th>Message</th></tr></thead><tbody>{issue_rows}</tbody></table>
  <h2>建议下一步操作</h2>
  <p>如存在 title_norm 或 file_name 噪声，先运行 refresh-metadata --dry-run，确认后再 --apply。</p>
</body>
</html>
"""


def _md_report(payload: dict[str, Any]) -> str:
    stats = payload["stats"]
    lines = [
        "# Post Rename Check",
        "",
        "本报告只检查数据库和文件系统一致性，不修改文件。",
        "",
        "## Summary",
        "",
        f"- errors: {stats['error_count']}",
        f"- warnings: {stats['warning_count']}",
        f"- missing files: {stats['missing_file_count']}",
        f"- dirty file_name: {stats['dirty_file_name_count']}",
        f"- dirty title_norm: {stats['dirty_title_norm_count']}",
        f"- metadata mismatch: {stats['metadata_mismatch_count']}",
        "",
        "## Issues",
        "",
        "| Severity | Code | Book ID | File | Path | Message |",
        "|---|---|---:|---|---|---|",
    ]
    for issue in payload["issues"]:
        lines.append(
            f"| {issue['severity']} | {issue['code']} | {issue.get('book_id') or ''} | "
            f"`{issue.get('file_name') or ''}` | `{issue.get('current_path') or ''}` | {issue['message']} |"
        )
    if not payload["issues"]:
        lines.append("| ok | - | - | - | - | No issues |")
    lines.extend(["", "## 建议下一步操作", "", "- 如存在标题元数据噪声，先运行 `refresh-metadata --dry-run`，确认后再 `--apply`。"])
    return "\n".join(lines).rstrip() + "\n"


def write_post_rename_check_reports(repo: Path, payload: dict[str, Any]) -> tuple[Path, Path, Path]:
    out_dir = repo / "reports" / "health"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"post_rename_check_{file_ts()}"
    html_path = out_dir / f"{stem}.html"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    index = 1
    while html_path.exists() or json_path.exists() or md_path.exists():
        stem_i = f"{stem}_{index}"
        html_path = out_dir / f"{stem_i}.html"
        json_path = out_dir / f"{stem_i}.json"
        md_path = out_dir / f"{stem_i}.md"
        index += 1
    html_path.write_text(_html_report(payload), encoding="utf-8")
    md_path.write_text(_md_report(payload), encoding="utf-8")
    write_json(json_path, payload)
    return html_path, json_path, md_path
