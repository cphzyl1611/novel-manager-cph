# Legado-like Reader Gap Analysis

## Legado (阅读3.0) reference capabilities

| Feature | Legado | NovelHub (current) | Gap |
|---------|--------|---------------------|-----|
| Local TXT import | Full import, scan, manage | Server-only | MAJOR |
| Bookshelf grid/list | Cover grid + list, drag sort | Simple text list | MAJOR |
| Reading UI | Immersive full-screen | Bare TextView | MAJOR |
| Font/theme picker | 10+ fonts, day/night/sepia | System font only | MAJOR |
| Line spacing | Precise control | Fixed lineSpacing=6f | MEDIUM |
| Page turn modes | Scroll, flip, cover, none | Button prev/next only | MAJOR |
| TOC | Native chapter list | AlertDialog list | MINOR |
| Offline reading | Full local cache | Chunked server pull | MEDIUM |
| Progress sync | WebDAV | LAN API | OK |
| Cover images | Local/online covers | None | MAJOR |
| Book detail page | Rich metadata | None | MAJOR |
| In-book search | Full-text | None | MAJOR |

## Current NovelHub Android weaknesses

1. **UI is debug-grade**: LinearLayout with no styling, no immersive mode
2. **No reading settings**: Font/theme/spacing hardcoded
3. **Naive pagination**: Fixed charsPerPage=1000, no screen-size awareness
4. **No local import**: Cannot open phone TXT files
5. **No covers**: Books are plain text cards
6. **No book detail**: No metadata, chapter preview, or reading stats
7. **English hardcoded strings**: All user-facing text in English
8. **Crash risks**: Unchecked casts, missing null guards

## Crash risk inventory (current)

| Location | Risk | Severity |
|----------|------|----------|
| MainActivity doSync | shelfLayout.getChildAt(0) after removeAllViews | HIGH |
| ReaderActivity displayPage | pageIndex OOB on empty pages | MEDIUM |
| ReaderActivity prevPage | chapterIndex-- without bounds when at ch 0 | LOW |
| ReaderActivity saveProgress | division by zero when totalChapters=0 | MEDIUM |

## Stability baseline (current phase)

- [x] Local-first startup
- [x] Content truncation fix (full file read via charset_normalizer)
- [x] Illegal Kotlin return fix
- [x] Crash hardening (null guards, coerceIn on indices)
- [x] Chinese UI localization
- [x] Content integrity end-to-end test

## Recommended phases

### Phase 1: Stability + Integrity (current)
Fix all crashes, verify content integrity, localize to Chinese.

### Phase 2: Reader enhancement
Immersive mode, tap-to-toggle-menu, gesture page turning, dynamic chars-per-page based on screen size, font size +/- controls, day/night/sepia themes, reading progress bar.

### Phase 3: Shelf UI
Grid layout option, book count and reading stats, swipe/long-press menu, last-read indicator, sort options.

### Phase 4: Reading settings
Font picker, theme picker with preview, line spacing slider, page turn animation mode, keep screen on toggle.

### Phase 5: Local TXT import
File picker for .txt files, local metadata extraction, local-only cache, merge with synced books when connected.

## What NOT to add

- EPUB rendering (requires engine rewrite)
- Online novel sources (against project charter)
- Cloud sync (LAN-only by design)
- TTS (nice-to-have, not core)
