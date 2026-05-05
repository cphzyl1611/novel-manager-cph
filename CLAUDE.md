# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Local TXT novel repository manager MVP. Scans local `.txt` folders, stores metadata in SQLite, then generates HTML/JSON/Markdown reports for duplicates, quality, chapters, and update candidates. All destructive actions require explicit `--confirm --yes-i-understand`; the tool never deletes files.

Python 3.10+. Entry point: `python run.py <command>`. CLI is argparse-based in `novel_manager/cli.py`.

## Commands

```bash
# Install
python -m pip install -r requirements.txt

# Run tests
pytest tests/ -v
pytest tests/test_quality.py -v          # single test file
pytest tests/test_quality.py -k test_ads # specific test

# Lint (not configured yet — only type annotations with `from __future__ import annotations`)
```

## Core pipeline

Each file goes through: **scan → metadata extraction → text cleaning → chapter parsing → quality scoring → DB upsert**.

```
run.py → cli.main() → cmd_* dispatch
                       ↓
scanner.py: iter_txt_files → detect_and_decode → extract_metadata → clean_text → parse_chapters → score_quality → upsert_book + replace_chapters
```

Key data flow: `scanner.scan_repo()` is the orchestrator. It calls into `text_cleaner.clean_text()`, `chapter_parser.parse_chapters()`, `quality.score_quality()` per file, then writes through `db.upsert_book()` / `db.replace_chapters()`.

## Module roles

| Module | Role |
|---|---|
| `cli.py` | Argparse CLI, all `cmd_*` functions, `build_parser()` |
| `scanner.py` | TXT discovery, encoding detection (charset_normalizer), per-file scan pipeline |
| `text_cleaner.py` | Ad-line removal, mojibake rate, text normalization (read-only, never modifies original) |
| `chapter_parser.py` | Regex-based chapter title detection (Chinese + English formats), ordering/duplicate/missing analysis |
| `quality.py` | Scores 0-100 across 5 dimensions: integrity, cleanliness, chapters, metadata, trust |
| `fingerprint.py` | SHA-256 hashing, title/author/chapter normalization (strip noise like "精校版", "笔趣阁") |
| `db.py` | SQLite schema (books, chapters, scan_errors, operations, duplicate_groups, work_groups, tags, series, update_candidates), connect/initialize/upsert |
| `duplicate_detector.py` | Exact duplicate detection by raw_sha256 and clean_sha256 grouping |
| `near_duplicate.py` | Fuzzy duplicate detection using rapidfuzz title similarity, chapter overlap, SimHash, Jaccard |
| `diagnose_near.py` | Debugging tool for near-duplicate misses — outputs pair-level diagnostic reports |
| `reports.py` | HTML/JSON report generation via Jinja2 templates (templates/ dir) |
| `report_index.py` | Index page listing all reports, find/open latest report |
| `summary_report.py` | Aggregated Markdown summary from duplicate + quality + error reports |
| `work_groups.py` | Group books representing same work, with set_primary/merge/split |
| `tag_manager.py` | CRUD for tags, auto-tagging, reading status management |
| `update_detector.py` | Compare incoming vs library to detect new/complete/better versions |
| `apply_updates.py` | Apply update candidates (move old→archive, new→library) with safety checks |
| `rename_planner.py` | Generate suggested filenames (title-author-status style) |
| `apply_renames.py` | Execute renames from rename plan, safety-bounded |
| `operations.py` | Stage duplicates from report (move to review_duplicates/) |
| `move_to_trash.py` | Move book to trash/ (never delete) |
| `metadata_tools.py` | Refresh title/author from filename without re-scanning, post-rename health check |
| `book_viewer.py` | list_books / inspect_book queries for CLI display |
| `config.py` | Repo directory structure, default cleaning/scoring rules, YAML config loading |
| `utils.py` | Path helpers, timestamp formatting, JSON read/write |

## Database

SQLite at `{repo}/db/novel_repo.sqlite`. Schema defined in `db.initialize()`. Key tables:
- `books` — scanned file metadata (SHA-256, quality scores, chapter counts)
- `chapters` — per-chapter parsing results, linked to `books.id`
- `scan_errors` — files that failed scanning
- `operations` — audit log of all moves/renames
- `duplicate_groups` / `duplicate_group_members` — exact & near duplicate results
- `work_groups` / `book_group_members` — same-work grouping
- `tags` / `book_tags` — tagging system
- `update_candidates` — version update proposals

Always use `db.connect(repo)` which enables foreign keys and row factory. Schema migrations don't exist yet — `CREATE TABLE IF NOT EXISTS`.

## Safety invariants

- Never delete files. "Delete" is move to `trash/`.
- Never overwrite files. Rename with suffix on conflict.
- Text cleaning is read-only — original TXT files are never modified.
- Destructive operations: `--dry-run` first, then `--confirm --yes-i-understand`.
- All moves write to `operations` table and `logs/operations.log`.
- Config at `config/cleaning_rules.yaml` controls ad keyword list (safe to edit and re-scan).

## Repository directory layout

```
{repo}/
  incoming/          # newly downloaded TXTs
  library/           # organized collection
  archive/replaced/  # old versions after update
  archive/duplicates/
  review_duplicates/ # staged for manual review
  review_updates/
  trash/             # soft-deleted files
  quarantine/        # files with issues
  reports/{duplicate,quality,errors,group,summary,update,rename,diagnostic,health}/
  db/novel_repo.sqlite + db/backups/
  config/{config.yaml,cleaning_rules.yaml,scoring_rules.yaml}
  logs/
  cache/
```

## Testing

Tests use plain `assert` (pytest). No fixtures or mocks — tests construct data directly. Test files match source modules (e.g., `test_quality.py` tests `quality.py`). 

## Note on this project

This project explicitly does NOT implement web scraping or online novel fetching. It is a local-only file manager. The README explicitly states this in its "明确不做的功能" section. Do not add any online fetching features.
