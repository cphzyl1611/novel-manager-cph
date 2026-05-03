from __future__ import annotations

import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


REPORT_TYPES = {
    "duplicate": "reports/duplicate",
    "quality": "reports/quality",
    "errors": "reports/errors",
    "summary": "reports/summary",
    "diagnostic": "reports/diagnostic",
    "update": "reports/update",
    "group": "reports/group",
    "rename": "reports/rename",
    "health": "reports/health",
}

DEFAULT_OPEN_ORDER = [
    ("summary", "md"),
    ("duplicate", "html"),
    ("quality", "html"),
    ("errors", "html"),
]


def _mtime_text(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def _report_type_for_path(repo: Path, path: Path) -> str:
    for report_type, relative in REPORT_TYPES.items():
        try:
            path.relative_to(repo / relative)
            return report_type
        except ValueError:
            continue
    return "unknown"


def _entry(repo: Path, path: Path) -> dict[str, Any]:
    return {
        "report_type": _report_type_for_path(repo, path),
        "file_name": path.name,
        "suffix": path.suffix.lstrip(".").lower(),
        "size": path.stat().st_size,
        "modified_time": _mtime_text(path),
        "mtime": path.stat().st_mtime,
        "path": str(path),
        "relative_path": str(path.relative_to(repo)).replace("\\", "/") if path.is_relative_to(repo) else str(path),
    }


def list_reports(
    repo: Path,
    *,
    report_type: str = "all",
    limit: int = 30,
    report_format: str = "all",
    latest_only: bool = False,
) -> list[dict[str, Any]]:
    types = REPORT_TYPES.keys() if report_type == "all" else [report_type]
    entries: list[dict[str, Any]] = []
    for item_type in types:
        report_dir = repo / REPORT_TYPES[item_type]
        if not report_dir.exists():
            continue
        files = [path for path in report_dir.iterdir() if path.is_file()]
        if report_format != "all":
            files = [path for path in files if path.suffix.lower() == f".{report_format}"]
        files = sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)
        if latest_only and files:
            files = files[:1]
        entries.extend(_entry(repo, path) for path in files)
    entries.sort(key=lambda item: item["mtime"], reverse=True)
    return entries[:limit]


def find_latest_report(repo: Path, *, report_type: str = "all", report_format: str | None = None) -> Path | None:
    candidates: list[dict[str, Any]] = []
    if report_type == "all":
        if report_format is not None:
            candidates = list_reports(repo, report_type="all", report_format=report_format, limit=1)
            return Path(candidates[0]["path"]) if candidates else None
        for item_type, suffix in DEFAULT_OPEN_ORDER:
            candidates = list_reports(repo, report_type=item_type, report_format=suffix, limit=1, latest_only=True)
            if candidates:
                return Path(candidates[0]["path"])
        return None
    preferred_format = report_format
    if preferred_format is None:
        preferred_format = "md" if report_type == "summary" else "html"
    candidates = list_reports(repo, report_type=report_type, report_format=preferred_format, limit=1, latest_only=True)
    if candidates:
        return Path(candidates[0]["path"])
    return None


def open_report(path: Path) -> tuple[bool, str]:
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
        return True, str(path)
    except Exception as exc:
        return False, f"{path} ({exc})"


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def _markdown_section(report_type: str, entries: list[dict[str, Any]]) -> list[str]:
    lines = [f"## {report_type}", ""]
    if not entries:
        lines.extend(["暂无", ""])
        return lines
    lines.extend(["| 文件名 | 类型 | 格式 | 大小 | 修改时间 | 相对路径 |", "|---|---|---|---:|---|---|"])
    for item in entries:
        rel = item["relative_path"]
        link = f"[{item['file_name']}]({rel})" if item["suffix"] in {"html", "md"} else item["file_name"]
        lines.append(
            f"| {link} | {item['report_type']} | {item['suffix']} | {_format_size(item['size'])} | {item['modified_time']} | `{rel}` |"
        )
    lines.append("")
    return lines


def _html_section(report_type: str, entries: list[dict[str, Any]]) -> str:
    if not entries:
        return f"<h2>{report_type}</h2><p>暂无</p>"
    rows = []
    for item in entries:
        rel = item["relative_path"]
        name = item["file_name"]
        if item["suffix"] in {"html", "md"}:
            name_html = f'<a href="{rel}">{name}</a>'
        else:
            name_html = name
        rows.append(
            "<tr>"
            f"<td>{name_html}</td><td>{item['report_type']}</td><td>{item['suffix']}</td>"
            f"<td>{_format_size(item['size'])}</td><td>{item['modified_time']}</td><td><code>{rel}</code></td>"
            "</tr>"
        )
    return (
        f"<h2>{report_type}</h2><table><thead><tr><th>文件名</th><th>类型</th><th>格式</th>"
        f"<th>大小</th><th>修改时间</th><th>相对路径</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def generate_report_index(repo: Path) -> tuple[Path, Path]:
    reports_dir = repo / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    by_type = {report_type: list_reports(repo, report_type=report_type, limit=1000) for report_type in REPORT_TYPES}

    md_lines = ["# 报告索引", "", f"- 生成时间：{generated}", f"- 仓库路径：`{repo}`", ""]
    for report_type in REPORT_TYPES:
        md_lines.extend(_markdown_section(report_type, by_type[report_type]))
    md_path = reports_dir / "index.md"
    md_path.write_text("\n".join(md_lines).rstrip() + "\n", encoding="utf-8")

    sections = "\n".join(_html_section(report_type, by_type[report_type]) for report_type in REPORT_TYPES)
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>报告索引</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #202124; }}
    h1 {{ font-size: 24px; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; }}
    th, td {{ border-bottom: 1px solid #eee; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f6f8fa; }}
    code {{ word-break: break-all; }}
  </style>
</head>
<body>
  <h1>报告索引</h1>
  <p>生成时间：{generated}</p>
  <p>仓库路径：<code>{repo}</code></p>
  {sections}
</body>
</html>
"""
    html_path = reports_dir / "index.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path, md_path
