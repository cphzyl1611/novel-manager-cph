from __future__ import annotations

import argparse
import shutil
import sqlite3
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .apply_renames import apply_renames_from_report
from .apply_updates import apply_updates_from_report
from .book_viewer import inspect_book, list_books
from .config import REPO_DIRS, create_default_configs, create_repo_dirs
from .db import connect, db_path, initialize
from .diagnose_near import diagnose_near
from .duplicate_detector import find_exact_duplicates
from .metadata_tools import post_rename_check, refresh_metadata, write_post_rename_check_reports
from .move_to_trash import move_book_to_trash, write_move_to_trash_log
from .near_duplicate import apply_near_duplicates, apply_near_to_work_groups, find_near_duplicates
from .operations import stage_duplicates_from_report
from .report_index import find_latest_report, generate_report_index, list_reports, open_report
from .reports import generate_duplicate_report, generate_error_report, generate_quality_report
from .rename_planner import build_rename_plan, write_rename_plan_reports
from .scanner import scan_repo
from .summary_report import generate_summary_report
from .tag_manager import (
    auto_tag,
    books_by_status,
    books_by_tag,
    create_tag,
    delete_tag,
    list_tags,
    set_reading_status,
    tag_book,
    untag_book,
)
from .update_detector import find_update_candidates, generate_update_report, save_update_candidates
from .utils import ensure_dir, file_ts, repo_path
from .work_groups import group_books, inspect_group, list_groups, merge_groups, set_primary, split_group

console = Console()


def _console_safe(value: object) -> str:
    text = str(value)
    encoding = getattr(console.file, "encoding", None) or "utf-8"
    try:
        return text.encode(encoding, errors="replace").decode(encoding)
    except LookupError:
        return text


def cmd_init(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    create_repo_dirs(repo)
    with connect(repo) as conn:
        initialize(conn)
    created = create_default_configs(repo)
    console.print(f"Initialized repo: {repo}")
    for path, was_created in created.items():
        console.print(f"{'created' if was_created else 'exists '} {path}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    ok = True
    checks: list[tuple[str, bool, str]] = []
    checks.append(("repo exists", repo.exists(), str(repo)))
    for relative in ["reports", "logs", "db", "config"]:
        checks.append((f"{relative} dir", (repo / relative).is_dir(), str(repo / relative)))
    for relative in ["config/config.yaml", "config/cleaning_rules.yaml", "config/scoring_rules.yaml"]:
        checks.append((relative, (repo / relative).is_file(), str(repo / relative)))
    db_ok = False
    try:
        with connect(repo) as conn:
            initialize(conn)
            conn.execute("SELECT 1").fetchone()
            db_ok = True
    except sqlite3.Error as exc:
        checks.append(("database read/write", False, str(exc)))
    else:
        checks.append(("database read/write", db_ok, str(db_path(repo))))
    for name, passed, detail in checks:
        ok = ok and passed
        console.print(f"[{'green' if passed else 'red'}]{'OK' if passed else 'FAIL'}[/] {name}: {detail}")
    return 0 if ok else 1


def cmd_scan(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        stats = scan_repo(
            conn,
            repo,
            args.area,
            changed_only=args.changed_only,
            force=args.force,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    console.print(stats)
    return 0


def cmd_find_duplicates(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    try:
        with connect(repo) as conn:
            initialize(conn)
            groups = []
            if args.mode in {"exact", "all"}:
                groups.extend(find_exact_duplicates(conn, args.area))
            if args.mode in {"near", "all"}:
                near_groups = find_near_duplicates(
                    conn,
                    area=args.area,
                    min_score=args.min_score,
                    high_confidence=args.high_confidence,
                    include_low_confidence=args.include_low_confidence,
                    limit=args.limit,
                )
                if args.apply:
                    apply_near_duplicates(conn, near_groups, min_score=args.min_score)
                    if args.apply_to_work_groups:
                        apply_near_to_work_groups(conn, near_groups)
                elif args.apply_to_work_groups:
                    console.print("--apply-to-work-groups requires --apply")
                    return 2
                groups.extend(near_groups)
    except sqlite3.Error as exc:
        console.print(f"查找重复失败：{exc}")
        return 1
    try:
        html_path, json_path = generate_duplicate_report(repo, groups)
    except OSError as exc:
        console.print(f"生成重复报告失败：{exc}")
        return 1
    console.print(f"duplicate groups: {len(groups)}")
    if args.mode in {"near", "all"} and not any(group.get("group_type") == "near_duplicate" for group in groups):
        console.print(f"未发现超过 min-score={args.min_score} 的近似重复候选。")
        console.print(f"建议尝试：python run.py diagnose-near --repo \"{repo}\" --query \"书名关键词\"")
        console.print(f"或：python run.py find-duplicates --repo \"{repo}\" --mode near --area {args.area} --include-low-confidence --min-score 0.65")
    console.print(f"HTML: {html_path}")
    console.print(f"JSON: {json_path}")
    return 0


def cmd_quality_report(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        html_path, json_path = generate_quality_report(conn, repo, args.area)
    console.print(f"HTML: {html_path}")
    console.print(f"JSON: {json_path}")
    return 0


def cmd_error_report(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        html_path, json_path = generate_error_report(conn, repo)
    console.print(f"HTML: {html_path}")
    console.print(f"JSON: {json_path}")
    return 0


def cmd_stage_duplicates(args: argparse.Namespace) -> int:
    if args.dry_run == args.confirm:
        console.print("Use exactly one of --dry-run or --confirm")
        return 2
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        results, apply_log = stage_duplicates_from_report(conn, repo, Path(args.report), dry_run=args.dry_run)
    for item in results:
        console.print(item)
    if apply_log:
        console.print(f"apply log: {apply_log}")
    return 0 if all(item.get("status") in {"dry_run", "success"} for item in results) else 1


def cmd_backup_db(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    source = db_path(repo)
    if not source.exists():
        console.print(f"database not found: {source}")
        return 1
    target = repo / "db" / "backups" / f"novel_repo_{file_ts()}.sqlite"
    ensure_dir(target.parent)
    shutil.copy2(source, target)
    console.print(f"backup: {target}")
    return 0


def cmd_summary_report(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    try:
        output = generate_summary_report(
            repo,
            duplicate_report=args.duplicate_report,
            quality_report=args.quality_report,
            error_report=args.error_report,
        )
    except OSError as exc:
        console.print(f"生成汇总报告失败：{exc}")
        return 1
    console.print(f"Markdown: {output}")
    return 0


def _short_hash(value: str | None, show_hash: bool) -> str:
    if not value:
        return ""
    return value if show_hash else value[:12]


def cmd_list_books(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        result = list_books(
            conn,
            area=args.area,
            limit=args.limit,
            sort=args.sort,
            descending=args.order_desc,
            min_quality=args.min_quality,
            max_quality=args.max_quality,
            query=args.query,
            poor_only=args.poor_only,
            problem_only=args.problem_only,
            tag=args.tag,
            status=args.status,
        )
    if result["total_books"] == 0:
        console.print("数据库还没有扫描数据，请先运行 scan。")
        return 0
    table = Table(title="Books")
    for column in [
        "book_id",
        "repo_area",
        "file_name",
        "title",
        "author",
        "quality_score",
        "quality_level",
        "reading_status",
        "tags",
        "chapter_count",
        "char_count_clean",
        "ad_line_count",
        "mojibake_rate",
        "current_path",
    ]:
        table.add_column(column)
    for row in result["rows"]:
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("repo_area") or ""),
            str(row.get("file_name") or ""),
            str(row.get("title_raw") or row.get("title_norm") or ""),
            str(row.get("author_raw") or row.get("author_norm") or ""),
            f"{float(row.get('quality_score') or 0):.2f}",
            str(row.get("quality_level") or ""),
            str(row.get("reading_status") or ""),
            ", ".join(row.get("tag_names", [])[:5]),
            str(row.get("chapter_count") or 0),
            str(row.get("char_count_clean") or 0),
            str(row.get("ad_line_count") or 0),
            f"{float(row.get('mojibake_rate') or 0):.4f}",
            str(row.get("current_path") or ""),
        )
    console.print(table)
    console.print(f"当前显示 {result['shown']} 本；数据库中符合条件总数 {result['total']} 本。")
    return 0


def cmd_inspect_book(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        result = inspect_book(
            conn,
            book_id=args.book_id,
            path=args.path,
            query=args.query,
            show_all_chapters=args.chapters,
            chapter_limit=args.chapter_limit,
        )
    if result["status"] != "ok":
        console.print(result["message"])
        if result["status"] == "candidates":
            table = Table(title="候选书籍")
            table.add_column("book_id")
            table.add_column("file_name")
            table.add_column("quality")
            table.add_column("path")
            for row in result["candidates"]:
                table.add_row(str(row.get("id")), str(row.get("file_name")), str(row.get("quality_score")), str(row.get("current_path")))
            console.print(table)
        return 0
    book = result["book"]
    sections = {
        "基本信息": ["id", "current_path", "original_path", "repo_area", "file_name", "file_size", "mtime", "status", "reading_status"],
        "识别信息": ["title_raw", "title_norm", "author_raw", "author_norm", "encoding", "encoding_confidence", "decode_status"],
        "内容指标": ["raw_sha256", "clean_sha256", "char_count_raw", "char_count_clean", "line_count_raw", "line_count_clean", "chapter_count"],
        "质量指标": [
            "quality_score",
            "quality_level",
            "mojibake_rate",
            "ad_line_count",
            "ad_line_rate",
            "duplicate_chapter_count",
            "missing_chapter_count",
            "chapter_order_error_count",
            "truncated_risk",
        ],
    }
    for title, fields in sections.items():
        table = Table(title=title)
        table.add_column("字段")
        table.add_column("值")
        for field in fields:
            value = book.get(field)
            if field in {"raw_sha256", "clean_sha256"}:
                value = _short_hash(value, args.show_hash)
            table.add_row(field if field != "id" else "book_id", "" if value is None else str(value))
        console.print(table)
    reasons = "\n".join(f"- {item}" for item in result["quality_reasons"]) or "无"
    console.print(Panel(reasons, title="quality_reasons"))
    tag_lines = [
        f"- {tag.get('name')} ({tag.get('category')}, {tag.get('source')}, {float(tag.get('confidence') or 0):.2f})"
        for tag in result.get("tags", [])
    ]
    console.print(Panel("\n".join(tag_lines) or "none", title="tags"))
    table = Table(title=f"章节预览（显示 {len(result['chapters'])}/{result['chapter_total']}）")
    for column in ["chapter_index", "chapter_no", "chapter_type", "title_raw", "char_count", "order_status"]:
        table.add_column(column)
    for chapter in result["chapters"]:
        table.add_row(
            str(chapter.get("chapter_index") or ""),
            str(chapter.get("chapter_no") or ""),
            str(chapter.get("chapter_type") or ""),
            str(chapter.get("title_raw") or ""),
            str(chapter.get("char_count") or 0),
            str(chapter.get("order_status") or ""),
        )
    console.print(table)
    return 0


def cmd_list_reports(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    reports = list_reports(
        repo,
        report_type=args.type,
        limit=args.limit,
        report_format=args.format,
        latest_only=args.latest_only,
    )
    table = Table(title="Reports")
    for column in ["report_type", "file_name", "suffix", "size", "modified_time", "path"]:
        table.add_column(column)
    for item in reports:
        table.add_row(
            item["report_type"],
            item["file_name"],
            item["suffix"],
            str(item["size"]),
            item["modified_time"],
            item["path"],
        )
    console.print(table)
    console.print(f"当前显示 {len(reports)} 个报告。")
    return 0


def cmd_open_latest_report(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    report = find_latest_report(repo, report_type=args.type, report_format=args.format)
    if report is None:
        console.print("没有找到可打开的报告。")
        return 1
    ok, message = open_report(report)
    if ok:
        console.print(f"opened: {message}")
    else:
        console.print(f"打开失败，请手动打开：{message}")
    return 0


def cmd_report_index(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    try:
        html_path, md_path = generate_report_index(repo)
    except OSError as exc:
        console.print(f"生成报告索引失败：{exc}")
        return 1
    console.print(f"HTML: {html_path}")
    console.print(f"Markdown: {md_path}")
    return 0


def cmd_group_books(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        try:
            result = group_books(
                conn,
                repo,
                area=args.area,
                apply=args.apply,
                dry_run=args.dry_run,
                min_confidence=args.min_confidence,
                include_low_confidence=args.include_low_confidence,
                limit=args.limit,
            )
        except OSError as exc:
            console.print(f"生成作品分组报告失败：{exc}")
            return 1
    console.print(f"候选分组：{len(result['candidates'])}")
    console.print(f"已写入分组：{len(result['applied_group_ids'])}")
    console.print(f"HTML: {result['html_path']}")
    console.print(f"JSON: {result['json_path']}")
    if args.dry_run:
        console.print("dry-run：未写入数据库。")
    elif not args.apply:
        console.print("默认模式：只生成报告，未写入数据库。")
    return 0


def cmd_diagnose_near(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    try:
        with connect(repo) as conn:
            initialize(conn)
            result = diagnose_near(
                conn,
                repo,
                area=args.area,
                query=args.query,
                min_candidate_title_score=args.min_candidate_title_score,
                limit=args.limit,
                include_exact=args.include_exact,
            )
    except (sqlite3.Error, OSError) as exc:
        console.print(f"生成近似重复诊断失败：{exc}")
        return 1
    console.print(f"候选对：{len(result['payload']['pairs'])}")
    console.print(f"HTML: {result['html_path']}")
    console.print(f"JSON: {result['json_path']}")
    console.print(f"Markdown: {result['md_path']}")
    return 0


def cmd_check_updates(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    try:
        with connect(repo) as conn:
            initialize(conn)
            result = find_update_candidates(
                conn,
                min_same_work_score=args.min_same_work_score,
                min_coverage=args.min_coverage,
                quality_tolerance=args.quality_tolerance,
                include_rejected=args.include_rejected,
                query=args.query,
                limit=args.limit,
                dry_run=args.dry_run,
            )
            saved = save_update_candidates(conn, result["candidates"]) if args.save_candidates and not args.dry_run else 0
        if args.dry_run:
            console.print(f"dry-run: incoming={result['incoming_count']}, library={result['library_count']}, pairs_to_check={result['pairs_to_check']}")
            return 0
        html_path, json_path, md_path = generate_update_report(repo, result, saved)
    except (sqlite3.Error, OSError) as exc:
        console.print(f"生成更新检测报告失败：{exc}")
        return 1
    if result["incoming_count"] == 0:
        console.print("未发现 incoming 文件，请先将新下载小说放入 incoming 并运行 scan --area incoming。")
    console.print(f"候选数量：{len(result['candidates'])}")
    console.print(f"HTML: {html_path}")
    console.print(f"JSON: {json_path}")
    console.print(f"Markdown: {md_path}")
    if saved:
        console.print(f"saved update_candidates: {saved}")
    return 0


def cmd_apply_updates(args: argparse.Namespace) -> int:
    if args.dry_run and args.confirm:
        console.print("--dry-run 和 --confirm 不能同时使用。")
        return 2
    if not args.dry_run and not args.confirm:
        console.print("请使用 --dry-run 预览，或使用 --confirm --yes-i-understand 执行。")
        return 2
    if args.confirm and not args.yes_i_understand:
        console.print("--confirm 需要同时提供 --yes-i-understand。")
        return 2
    repo = repo_path(args.repo)
    try:
        with connect(repo) as conn:
            initialize(conn)
            result = apply_updates_from_report(
                conn,
                repo,
                Path(args.report),
                dry_run=args.dry_run,
                confirm=args.confirm,
                min_same_work_score=args.min_same_work_score,
                min_coverage=args.min_coverage,
                max_quality_drop=args.max_quality_drop,
                allow_risk=args.allow_risk,
                limit=args.limit,
            )
    except (OSError, sqlite3.Error, ValueError) as exc:
        console.print(f"应用更新失败：{exc}")
        return 1
    console.print(f"planned: {result['planned_count']}; applied: {result['applied_count']}; skipped: {result['skipped_count']}; failed: {result['failed_count']}")
    console.print(f"apply log: {result['log_path']}")
    for item in result["items"]:
        console.print(_console_safe(item))
    return 0 if result["failed_count"] == 0 else 1


def cmd_apply_renames(args: argparse.Namespace) -> int:
    if args.dry_run and args.confirm:
        console.print("--dry-run and --confirm cannot be used together.")
        return 2
    if not args.dry_run and not args.confirm:
        console.print("Use --dry-run to preview, or --confirm --yes-i-understand to execute.")
        return 2
    if args.confirm and not args.yes_i_understand:
        console.print("--confirm requires --yes-i-understand.")
        return 2
    repo = repo_path(args.repo)
    try:
        with connect(repo) as conn:
            result = apply_renames_from_report(
                conn,
                repo,
                Path(args.report),
                dry_run=args.dry_run,
                confirm=args.confirm,
                limit=args.limit,
                allow_duplicate_book_group=args.allow_duplicate_book_group,
                allow_author_missing=args.allow_author_missing,
            )
    except (OSError, sqlite3.Error, ValueError) as exc:
        console.print(f"apply-renames failed: {exc}")
        return 1
    console.print(
        f"planned: {result['planned_count']}; renamed: {result['renamed_count']}; "
        f"skipped: {result['skipped_count']}; failed: {result['failed_count']}"
    )
    console.print(f"apply log: {result['log_path']}")
    for item in result["items"]:
        console.print(_console_safe(item))
    return 0 if result["failed_count"] == 0 else 1


def _print_book_rows(rows: list[dict], title: str) -> None:
    table = Table(title=title)
    for column in ["book_id", "file_name", "title", "author", "repo_area", "quality_score", "chapter_count", "current_path"]:
        table.add_column(column)
    for row in rows:
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("file_name") or ""),
            str(row.get("title_raw") or row.get("title_norm") or ""),
            str(row.get("author_raw") or row.get("author_norm") or ""),
            str(row.get("repo_area") or ""),
            f"{float(row.get('quality_score') or 0):.2f}",
            str(row.get("chapter_count") or 0),
            str(row.get("current_path") or ""),
        )
    console.print(table)
    console.print(f"shown: {len(rows)}")


def cmd_list_tags(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        rows = list_tags(conn, category=args.category, query=args.query)
    table = Table(title="Tags")
    for column in ["tag_id", "name", "category", "description", "book_count", "created_at"]:
        table.add_column(column)
    for row in rows:
        table.add_row(str(row.get("tag_id")), str(row.get("name") or ""), str(row.get("category") or ""), str(row.get("description") or ""), str(row.get("book_count") or 0), str(row.get("created_at") or ""))
    console.print(table)
    console.print(f"shown: {len(rows)}")
    return 0


def cmd_create_tag(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        result = create_tag(conn, repo, name=args.name, category=args.category, description=args.description)
    console.print(result)
    return 0


def cmd_delete_tag(args: argparse.Namespace) -> int:
    if args.dry_run and args.confirm:
        console.print("--dry-run and --confirm cannot be used together")
        return 2
    if not args.dry_run and not args.confirm:
        console.print("use --dry-run or --confirm")
        return 2
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        result = delete_tag(conn, repo, tag=args.tag, dry_run=args.dry_run, confirm=args.confirm)
    console.print(result)
    return 0


def cmd_tag_book(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        result = tag_book(conn, repo, book_id=args.book_id, tag=args.tag, source=args.source, create=args.create)
    console.print(result)
    return 0 if result["status"] in {"tagged", "exists"} else 1


def cmd_untag_book(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        result = untag_book(conn, repo, book_id=args.book_id, tag=args.tag)
    console.print(result)
    return 0 if result["status"] in {"untagged", "relation_not_found"} else 1


def cmd_books_by_tag(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        rows = books_by_tag(conn, tag=args.tag, area=args.area, limit=args.limit, sort=args.sort, descending=args.order_desc)
    _print_book_rows(rows, f"Books by tag: {args.tag}")
    return 0


def cmd_set_status(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        result = set_reading_status(conn, repo, book_id=args.book_id, status=args.status, allow_custom_status=args.allow_custom_status)
    console.print(result)
    return 0 if result["status"] == "updated" else 1


def cmd_books_by_status(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        rows = books_by_status(conn, status=args.status, area=args.area, limit=args.limit, sort=args.sort, descending=args.order_desc)
    _print_book_rows(rows, f"Books by status: {args.status}")
    return 0


def cmd_auto_tag(args: argparse.Namespace) -> int:
    if args.dry_run and args.apply:
        console.print("--dry-run and --apply cannot be used together")
        return 2
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        result = auto_tag(conn, repo, dry_run=not args.apply, apply=args.apply)
    console.print(f"suggestions: {len(result['suggestions'])}; applied: {result['applied']}; dry_run: {result['dry_run']}")
    for item in result["suggestions"][:100]:
        console.print(item)
    return 0


def cmd_rename_plan(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    try:
        with connect(repo) as conn:
            payload = build_rename_plan(
                conn,
                repo,
                area=args.area,
                query=args.query,
                limit=args.limit,
                include_unchanged=args.include_unchanged,
                style=args.style,
                unknown_author=args.unknown_author,
                max_length=args.max_length,
                include_unknown_author=args.include_unknown_author,
                max_status_count=args.max_status_count,
            )
        html_path, json_path, md_path = write_rename_plan_reports(repo, payload)
    except (sqlite3.Error, OSError) as exc:
        console.print(f"生成重命名计划失败：{exc}")
        return 1
    console.print("本命令只生成计划，不改名。")
    console.print(f"rename_recommended: {payload['stats']['rename_recommended']}; manual_review: {payload['stats']['manual_review']}; no_change: {payload['stats']['no_change']}")
    console.print(f"HTML: {html_path}")
    console.print(f"JSON: {json_path}")
    console.print(f"Markdown: {md_path}")
    return 0


def cmd_refresh_metadata(args: argparse.Namespace) -> int:
    if args.dry_run and args.apply:
        console.print("--dry-run and --apply cannot be used together.")
        return 2
    if not args.dry_run and not args.apply:
        console.print("Use --dry-run to preview, or --apply to update database metadata.")
        return 2
    repo = repo_path(args.repo)
    try:
        with connect(repo) as conn:
            result = refresh_metadata(
                conn,
                repo,
                area=args.area,
                query=args.query,
                book_id=args.book_id,
                dry_run=args.dry_run,
                apply=args.apply,
                limit=args.limit,
            )
    except (sqlite3.Error, ValueError) as exc:
        console.print(f"refresh-metadata failed: {exc}")
        return 1
    console.print(
        f"total: {result['total']}; would_update: {result['change_count']}; updated: {result['updated_count']}; "
        f"no_change: {result['no_change_count']}; skipped: {result['skipped_count']}"
    )
    for item in result["items"]:
        console.print(
            _console_safe(
                {
                    "book_id": item.get("book_id"),
                    "status": item.get("status"),
                    "old_title_norm": item.get("old_title_norm"),
                    "new_title_norm": item.get("new_title_norm"),
                    "changes": item.get("changes"),
                    "skip_reason": item.get("skip_reason"),
                }
            )
        )
    return 0


def cmd_post_rename_check(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    try:
        with connect(repo) as conn:
            payload = post_rename_check(conn, repo)
        html_path, json_path, md_path = write_post_rename_check_reports(repo, payload)
    except (sqlite3.Error, OSError) as exc:
        console.print(f"post-rename-check failed: {exc}")
        return 1
    stats = payload["stats"]
    console.print(
        f"errors: {stats['error_count']}; warnings: {stats['warning_count']}; "
        f"missing_file: {stats['missing_file_count']}; dirty_title_norm: {stats['dirty_title_norm_count']}"
    )
    console.print(f"HTML: {html_path}")
    console.print(f"JSON: {json_path}")
    console.print(f"Markdown: {md_path}")
    return 0


def cmd_move_to_trash(args: argparse.Namespace) -> int:
    if args.dry_run and args.confirm:
        console.print("--dry-run 和 --confirm 不能同时使用。")
        return 2
    if not args.dry_run and not args.confirm:
        console.print("请先使用 --dry-run 预览，或使用 --confirm --yes-i-understand 执行。")
        return 2
    if args.confirm and not args.yes_i_understand:
        console.print("--confirm 需要同时提供 --yes-i-understand。")
        return 2
    repo = repo_path(args.repo)
    try:
        with connect(repo) as conn:
            result = move_book_to_trash(conn, repo, args.book_id, dry_run=args.dry_run, confirm=args.confirm)
        log_path = write_move_to_trash_log(repo, result)
    except (sqlite3.Error, OSError, ValueError) as exc:
        console.print(f"移入废弃区失败：{exc}")
        return 1
    console.print(_console_safe(result))
    console.print(f"log: {log_path}")
    return 0 if result.get("status") in {"dry_run", "success"} else 1


def cmd_list_groups(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        groups = list_groups(conn, limit=args.limit, query=args.query, sort=args.sort, descending=args.order_desc, include_empty=args.empty)
    table = Table(title="Work Groups")
    for column in ["group_id", "canonical_title", "canonical_author", "primary_book_id", "member_count", "group_confidence", "group_source", "updated_at"]:
        table.add_column(column)
    for group in groups:
        table.add_row(
            str(group.get("group_id")),
            str(group.get("canonical_title") or ""),
            str(group.get("canonical_author") or ""),
            str(group.get("primary_book_id") or ""),
            str(group.get("member_count") or 0),
            f"{float(group.get('group_confidence') or 0):.2f}",
            str(group.get("group_source") or ""),
            str(group.get("updated_at") or ""),
        )
    console.print(table)
    console.print(f"当前显示 {len(groups)} 个作品组。")
    return 0


def cmd_inspect_group(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        result = inspect_group(conn, args.group_id)
    if result["status"] != "ok":
        console.print(result["message"])
        return 0
    group = result["group"]
    table = Table(title="作品组信息")
    table.add_column("字段")
    table.add_column("值")
    for field in ["id", "canonical_title", "canonical_author", "primary_book_id", "group_confidence", "group_source", "description"]:
        table.add_row("group_id" if field == "id" else field, str(group.get(field) or ""))
    console.print(table)
    members = Table(title="成员列表")
    for column in ["book_id", "role", "confidence", "source", "file_name", "current_path", "quality_score", "quality_level", "chapter_count", "char_count_clean", "ad_line_count", "mojibake_rate"]:
        members.add_column(column)
    for member in result["members"]:
        path = str(member.get("current_path") or "")
        if not args.show_path and len(path) > 60:
            path = path[:57] + "..."
        members.add_row(
            str(member.get("book_id")),
            str(member.get("role") or ""),
            f"{float(member.get('confidence') or 0):.2f}",
            str(member.get("source") or ""),
            str(member.get("file_name") or ""),
            path,
            str(member.get("quality_score") or ""),
            str(member.get("quality_level") or ""),
            str(member.get("chapter_count") or 0),
            str(member.get("char_count_clean") or 0),
            str(member.get("ad_line_count") or 0),
            f"{float(member.get('mojibake_rate') or 0):.4f}",
        )
    console.print(members)
    console.print(Panel("\n".join(result["primary_reasons"]) or "暂无", title="推荐主版本理由"))
    return 0


def cmd_set_primary(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        result = set_primary(conn, args.group_id, args.book_id)
    console.print(result["message"])
    return 0 if result["status"] == "ok" else 1


def cmd_merge_groups(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        result = merge_groups(conn, args.source_group_id, args.target_group_id)
    console.print(result["message"])
    return 0 if result["status"] == "ok" else 1


def cmd_split_group(args: argparse.Namespace) -> int:
    repo = repo_path(args.repo)
    with connect(repo) as conn:
        initialize(conn)
        result = split_group(conn, args.book_id)
    console.print(result["message"])
    if result["status"] == "ok":
        console.print(f"old_group_id: {result['old_group_id']}; new_group_id: {result['new_group_id']}")
    return 0 if result["status"] == "ok" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="novel_repo_manager")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init")
    p.add_argument("--repo", required=True)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("doctor")
    p.add_argument("--repo", required=True)
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("scan")
    p.add_argument("--repo", required=True)
    p.add_argument("--area", choices=["library", "incoming", "all"], required=True)
    p.add_argument("--changed-only", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("find-duplicates")
    p.add_argument("--repo", required=True)
    p.add_argument("--mode", choices=["exact", "near", "all"], required=True)
    p.add_argument("--area", choices=["library", "incoming", "all"], required=True)
    p.add_argument("--min-score", type=float, default=0.82)
    p.add_argument("--high-confidence", type=float, default=0.90)
    p.add_argument("--include-low-confidence", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--apply-to-work-groups", action="store_true")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_find_duplicates)

    p = sub.add_parser("quality-report")
    p.add_argument("--repo", required=True)
    p.add_argument("--area", choices=["library", "incoming", "all"], required=True)
    p.set_defaults(func=cmd_quality_report)

    p = sub.add_parser("error-report")
    p.add_argument("--repo", required=True)
    p.set_defaults(func=cmd_error_report)

    p = sub.add_parser("stage-duplicates")
    p.add_argument("--repo", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--confirm", action="store_true")
    p.set_defaults(func=cmd_stage_duplicates)

    p = sub.add_parser("backup-db")
    p.add_argument("--repo", required=True)
    p.set_defaults(func=cmd_backup_db)

    p = sub.add_parser("summary-report")
    p.add_argument("--repo", required=True)
    p.add_argument("--duplicate-report")
    p.add_argument("--quality-report")
    p.add_argument("--error-report")
    p.set_defaults(func=cmd_summary_report)

    p = sub.add_parser("list-books")
    p.add_argument("--repo", required=True)
    p.add_argument("--area", choices=["library", "incoming", "all"], default="all")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument(
        "--sort",
        choices=["quality", "file_name", "chapter_count", "char_count", "ad_line_count", "mojibake_rate", "updated_at"],
        default="updated_at",
    )
    order = p.add_mutually_exclusive_group()
    order.add_argument("--desc", dest="order_desc", action="store_true", default=True)
    order.add_argument("--asc", dest="order_desc", action="store_false")
    p.add_argument("--min-quality", type=float, default=0)
    p.add_argument("--max-quality", type=float, default=100)
    p.add_argument("--query")
    p.add_argument("--poor-only", action="store_true")
    p.add_argument("--problem-only", action="store_true")
    p.add_argument("--tag")
    p.add_argument("--status")
    p.set_defaults(func=cmd_list_books)

    p = sub.add_parser("inspect-book")
    p.add_argument("--repo", required=True)
    p.add_argument("--book-id", type=int)
    p.add_argument("--path")
    p.add_argument("--query")
    p.add_argument("--chapters", action="store_true")
    p.add_argument("--chapter-limit", type=int, default=30)
    p.add_argument("--show-hash", action="store_true")
    p.set_defaults(func=cmd_inspect_book)

    p = sub.add_parser("list-reports")
    p.add_argument("--repo", required=True)
    p.add_argument("--type", choices=["duplicate", "quality", "errors", "summary", "update", "group", "diagnostic", "rename", "health", "all"], default="all")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--format", choices=["html", "json", "md", "all"], default="all")
    p.add_argument("--latest-only", action="store_true")
    p.set_defaults(func=cmd_list_reports)

    p = sub.add_parser("open-latest-report")
    p.add_argument("--repo", required=True)
    p.add_argument("--type", choices=["summary", "duplicate", "quality", "errors", "all"], default="all")
    p.add_argument("--format", choices=["md", "html", "json"])
    p.set_defaults(func=cmd_open_latest_report)

    p = sub.add_parser("report-index")
    p.add_argument("--repo", required=True)
    p.set_defaults(func=cmd_report_index)

    p = sub.add_parser("group-books")
    p.add_argument("--repo", required=True)
    p.add_argument("--area", choices=["library", "incoming", "all"], default="all")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--min-confidence", type=float, default=0.85)
    p.add_argument("--include-low-confidence", action="store_true")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_group_books)

    p = sub.add_parser("diagnose-near")
    p.add_argument("--repo", required=True)
    p.add_argument("--area", choices=["library", "incoming", "all"], default="all")
    p.add_argument("--query")
    p.add_argument("--min-candidate-title-score", type=float, default=0.70)
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--include-exact", action="store_true")
    p.add_argument("--show-rejected", action="store_true")
    p.set_defaults(func=cmd_diagnose_near)

    p = sub.add_parser("check-updates")
    p.add_argument("--repo", required=True)
    p.add_argument("--min-same-work-score", type=float, default=0.75)
    p.add_argument("--min-coverage", type=float, default=0.80)
    p.add_argument("--quality-tolerance", type=float, default=5)
    p.add_argument("--include-rejected", action="store_true")
    p.add_argument("--query")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--save-candidates", action="store_true")
    p.set_defaults(func=cmd_check_updates)

    p = sub.add_parser("apply-updates")
    p.add_argument("--repo", required=True)
    p.add_argument("--report", required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirm", action="store_true")
    p.add_argument("--min-same-work-score", type=float, default=0.85)
    p.add_argument("--min-coverage", type=float, default=0.90)
    p.add_argument("--max-quality-drop", type=float, default=5)
    p.add_argument("--allow-risk", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--yes-i-understand", action="store_true")
    p.set_defaults(func=cmd_apply_updates)

    p = sub.add_parser("list-tags")
    p.add_argument("--repo", required=True)
    p.add_argument("--category", choices=["genre", "status", "quality", "source", "custom", "all"], default="all")
    p.add_argument("--query")
    p.set_defaults(func=cmd_list_tags)

    p = sub.add_parser("create-tag")
    p.add_argument("--repo", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--category", choices=["genre", "status", "quality", "source", "custom"], default="custom")
    p.add_argument("--description")
    p.set_defaults(func=cmd_create_tag)

    p = sub.add_parser("delete-tag")
    p.add_argument("--repo", required=True)
    p.add_argument("--tag", required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirm", action="store_true")
    p.set_defaults(func=cmd_delete_tag)

    p = sub.add_parser("tag-book")
    p.add_argument("--repo", required=True)
    p.add_argument("--book-id", type=int, required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--source", choices=["manual", "auto"], default="manual")
    p.add_argument("--create", action="store_true")
    p.set_defaults(func=cmd_tag_book)

    p = sub.add_parser("untag-book")
    p.add_argument("--repo", required=True)
    p.add_argument("--book-id", type=int, required=True)
    p.add_argument("--tag", required=True)
    p.set_defaults(func=cmd_untag_book)

    p = sub.add_parser("books-by-tag")
    p.add_argument("--repo", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--area", choices=["library", "incoming", "archive", "all"], default="all")
    p.add_argument("--sort", choices=["quality", "file_name", "updated_at"], default="updated_at")
    order = p.add_mutually_exclusive_group()
    order.add_argument("--desc", dest="order_desc", action="store_true", default=True)
    order.add_argument("--asc", dest="order_desc", action="store_false")
    p.set_defaults(func=cmd_books_by_tag)

    p = sub.add_parser("set-status")
    p.add_argument("--repo", required=True)
    p.add_argument("--book-id", type=int, required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--allow-custom-status", action="store_true")
    p.set_defaults(func=cmd_set_status)

    p = sub.add_parser("books-by-status")
    p.add_argument("--repo", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--area", choices=["library", "incoming", "archive", "all"], default="all")
    p.add_argument("--sort", choices=["quality", "file_name", "updated_at"], default="updated_at")
    order = p.add_mutually_exclusive_group()
    order.add_argument("--desc", dest="order_desc", action="store_true", default=True)
    order.add_argument("--asc", dest="order_desc", action="store_false")
    p.set_defaults(func=cmd_books_by_status)

    p = sub.add_parser("auto-tag")
    p.add_argument("--repo", required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_auto_tag)

    p = sub.add_parser("rename-plan")
    p.add_argument("--repo", required=True)
    p.add_argument("--area", choices=["library", "incoming", "archive", "all"], default="library")
    p.add_argument("--query")
    p.add_argument("--limit", type=int)
    p.add_argument("--include-unchanged", action="store_true")
    p.add_argument("--style", choices=["title-author-status", "title-author", "title-only"], default="title-author-status")
    p.add_argument("--unknown-author", default="未知作者")
    p.add_argument("--include-unknown-author", action="store_true")
    p.add_argument("--max-status-count", type=int, default=2)
    p.add_argument("--max-length", type=int, default=120)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_rename_plan)

    p = sub.add_parser("refresh-metadata")
    p.add_argument("--repo", required=True)
    p.add_argument("--area", choices=["library", "incoming", "archive", "review_duplicates", "all"], default="library")
    p.add_argument("--query")
    p.add_argument("--book-id", type=int)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_refresh_metadata)

    p = sub.add_parser("post-rename-check")
    p.add_argument("--repo", required=True)
    p.set_defaults(func=cmd_post_rename_check)

    p = sub.add_parser("move-to-trash")
    p.add_argument("--repo", required=True)
    p.add_argument("--book-id", type=int, required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirm", action="store_true")
    p.add_argument("--yes-i-understand", action="store_true")
    p.set_defaults(func=cmd_move_to_trash)

    p = sub.add_parser("apply-renames")
    p.add_argument("--repo", required=True)
    p.add_argument("--report", required=True)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirm", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--allow-duplicate-book-group", action="store_true")
    p.add_argument("--allow-author-missing", action="store_true", default=True)
    p.add_argument("--yes-i-understand", action="store_true")
    p.set_defaults(func=cmd_apply_renames)

    p = sub.add_parser("list-groups")
    p.add_argument("--repo", required=True)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--query")
    p.add_argument("--sort", choices=["updated_at", "member_count", "group_confidence", "title"], default="updated_at")
    group_order = p.add_mutually_exclusive_group()
    group_order.add_argument("--desc", dest="order_desc", action="store_true", default=True)
    group_order.add_argument("--asc", dest="order_desc", action="store_false")
    p.add_argument("--empty", action="store_true")
    p.set_defaults(func=cmd_list_groups)

    p = sub.add_parser("inspect-group")
    p.add_argument("--repo", required=True)
    p.add_argument("--group-id", type=int, required=True)
    p.add_argument("--show-path", action="store_true")
    p.set_defaults(func=cmd_inspect_group)

    p = sub.add_parser("set-primary")
    p.add_argument("--repo", required=True)
    p.add_argument("--group-id", type=int, required=True)
    p.add_argument("--book-id", type=int, required=True)
    p.set_defaults(func=cmd_set_primary)

    p = sub.add_parser("merge-groups")
    p.add_argument("--repo", required=True)
    p.add_argument("--source-group-id", type=int, required=True)
    p.add_argument("--target-group-id", type=int, required=True)
    p.set_defaults(func=cmd_merge_groups)

    p = sub.add_parser("split-group")
    p.add_argument("--repo", required=True)
    p.add_argument("--book-id", type=int, required=True)
    p.set_defaults(func=cmd_split_group)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
