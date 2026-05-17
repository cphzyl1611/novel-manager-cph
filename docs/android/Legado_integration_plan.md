# Legado Integration Plan for NovelHub Android

## 1. Why abandon current self-built Android Reader

The custom reader (`android_app/`) accumulated 10+ commits fixing compilation errors,
string escaping bugs, crash guards, swipe gestures, and content truncation. Despite
these fixes, the reader remains:

- **Structurally limited**: LinearLayout + TextView with manual pagination
- **Unstable**: Content truncation persisted across multiple fix attempts
- **Missing core features**: No themes, no font selection, no EPUB, no TTS, no cover display
- **Not NovelHub's strength**: Building a Legado-quality reader takes months of dedicated
  Android UI work. NovelHub's core competency is PC-side TXT management, dedup, and LAN sync.

Legado already solves reading UX. NovelHub should focus on what it does uniquely.

## 2. Why Legado

- 17K+ commits, active community, Play Store releases
- Cover grid/list bookshelf, immersive paging (scroll/cover/simulate/none),
  font/theme/spacing/background, TOC, bookmarks, replace rules, TTS, EPUB/MOBI/TXT
- Extensible BookSource engine with rule-based content retrieval
- Room database: clean Book/BookChapter/BookSource entities
- GPL-3.0: can fork and modify as long as derivative works remain GPL

## 3. GPL-3.0 License impact

| Aspect | Impact |
|--------|--------|
| Fork/modify Legado | Allowed, derivative MUST remain GPL-3.0 |
| Distribute modified APK | Must provide GPL-3.0 source |
| Link with proprietary code | Linked code becomes GPL-3.0 (viral) |
| **NovelHub server** | NOT affected — communicates over HTTP API |
| **Web/PWA** | NOT affected — separate process, network boundary |
| **API as integration boundary** | Clean: Legado (GPL) ↔ HTTP ↔ NovelHub (your license) |

## 4. Directory structure

```
android_app/          # OLD reader (preserved, not deleted)
android_legado/
  legado/              # Upstream Legado (git clone, unmodified)
  NovelHubSync/        # Future GPL-3.0 module (if forking)
novel_manager/         # Python server (unchanged)
```

## 5. Legado build status

- **Cloned**: Successfully at `android_legado/legado`
- **gradlew.bat**: Exists
- **JDK**: Java 25 detected (major version 69) — TOO NEW
- **Android SDK**: Available in user environment
- **Build**: Failed with `Unsupported class file major version 69`
  - Root cause: Java 25 is incompatible with Gradle 8.x. Gradle 8.x supports JDK 17-21.
  - This is NOT a Legado code issue — it's a JDK version mismatch.
- Required: JDK 17 or JDK 21 (not 25)
- PowerShell fix:
  ```powershell
  $env:JAVA_HOME = "D:\Java\jdk-17"
  $env:Path = "$env:JAVA_HOME\bin;$env:Path"
  java -version
  cd android_legado\legado
  .\gradlew.bat --stop
  .\gradlew.bat assembleDebug --stacktrace
  ```
- After switching to JDK 17/21, `assembleDebug` is expected to succeed.

## 6. Key module map

| Module | Package | Purpose |
|--------|---------|---------|
| Book entity | `data.entities.Book` | Room: bookUrl, name, author, type, durChapterIndex |
| Chapter entity | `data.entities.BookChapter` | Room: bookUrl(FK), index, title, url, start, end |
| BookSource | `data.entities.BookSource` | Rule-based: search/toc/content/info rules |
| BaseSource | `data.entities.rule.BaseSource` | Interface for book sources |
| Local TXT import | `model.localBook.LocalBook` | TXT/EPUB parsing, encoding detection |
| LocalBookParse | `model.localBook.BaseLocalBookParse` | Interface: upBookInfo, getChapterList, getContent |
| Read model | `model.ReadBook` | Active reading state (book, chapter, page) |
| Bookshelf UI | `ui.main.bookshelf` | Grid/list bookshelf |
| Read UI | `ui.book.read` | Reading activity with paging |
| WebDav | `lib.permissions.WebDav` | Backup/restore support |

## 7. Approach A: NovelHub as Legado BookSource (minimum invasion)

Create a custom BookSource that treats NovelHub API as a content provider.

**How it works:**
- NovelHub backend serves a BookSource JSON via `/api/legado/source`
- Legado imports this source URL
- Searching/browsing/toc/reading all go through the BookSource rules
- Each API call maps to a Legado BookSource rule: search→`/search`, toc→`/toc`, content→`/content`

**Pros:** Zero Legado code changes, just a JSON config. Low maintenance. Fast POC.
**Cons:** Progress sync one-way only. No auth token support. User configures URL manually.

**Effort:** 2-3 days

## 8. Approach B: Fork Legado + NovelHubSync module (deep integration)

Fork Legado, add a sync module in `modules/novelhub-sync/`.

**How it works:**
- Adds server URL + device token to AppConfig
- `NovelHubSyncService` syncs books/chapters/progress via existing `/api/mobile/*` endpoints
- Books tagged with `origin = "novelhub"` in Room
- "NovelHub Sync" entry in settings/side drawer

**Pros:** Bidirectional progress sync. Auto server config. True local-first reading.
**Cons:** Must maintain fork. GPL-3.0 applies to all modifications. Larger code surface.

**Effort:** 4-6 weeks

## 9. Recommendation

**Start with Approach A, validate, graduate to B if needed.**

## 10. Phase 1: NovelHub BookSource (minimum viable)

1. NovelHub server exposes `/api/legado/source` → BookSource JSON
2. User imports `http://192.168.1.x:8765/api/legado/source` in Legado
3. NovelHub books appear in Legado bookshelf/explore
4. Reading works; chapters load on demand

## 11. Phase 2: Progress sync (fork)

1. Fork Legado
2. Add NovelHub sync module
3. POST progress on chapter/page change
4. Pull progress on startup

## 12. NovelHub backend changes

### For Approach A:
```
GET /api/legado/source          → BookSource JSON
GET /api/legado/search?key=X    → search results
GET /api/legado/book-info       → book detail
GET /api/legado/toc             → chapter list
GET /api/legado/content         → chapter content
```

### For Approach B:
Existing `/api/mobile/*` endpoints are sufficient.

## 13. Risk checklist

- GPL-3.0 contamination if Approach B code boundary is unclear
- Legado upstream breaking changes on fork
- Encoding across API boundary (GBK/GB18030→UTF-8)
- Auth token storage in Legado sandbox model
- Network timeout on slow LAN

## 14. Phase A API Design — NovelHub as Legado BookSource

### Design rationale

Legado's book source engine supports JSONPath rules for parsing structured API responses.
NovelHub already returns clean JSON from `/api/mobile/*`. Instead of modifying Legado,
we create a thin `/api/legado/*` adapter that repackages existing data into the format
Legado's JSONPath rules expect.

### API endpoints

All endpoints live under `/api/legado/`. No auth required (LAN-only, same as Web/PWA).

```
GET  /api/legado/source              → BookSource JSON (importable in Legado)
POST /api/legado/search              → search results in Legado format
GET  /api/legado/book-info           → single book detail
GET  /api/legado/toc                 → chapter list
GET  /api/legado/content             → chapter content text
```

### 14.1 GET /api/legado/source

Returns a Legado-compatible BookSource JSON. User imports this URL in Legado:
Book Sources → Import → URL → `http://192.168.1.x:8765/api/legado/source`

```json
{
  "bookSourceUrl": "http://SERVER/api/legado",
  "bookSourceName": "NovelHub",
  "bookSourceGroup": "局域网",
  "bookSourceType": 0,
  "bookSourceComment": "电脑端 NovelHub 书库",
  "enabled": true,
  "ruleSearch": {
    "searchUrl": "http://SERVER/api/legado/search?key={{key}}&page={{page}}",
    "bookList": "$.items[*]",
    "name": "$.title",
    "author": "$.author",
    "kind": "$.chapter_count",
    "lastChapter": "$.latest_read_at",
    "bookUrl": "$.book_id",
    "coverUrl": ""
  },
  "ruleBookInfo": {
    "name": "$.title",
    "author": "$.author",
    "coverUrl": "",
    "intro": "$.description",
    "tocUrl": "$.book_id"
  },
  "ruleToc": {
    "chapterList": "$.chapters[*]",
    "chapterName": "$.title",
    "chapterUrl": "$.index"
  },
  "ruleContent": {
    "content": "$.content"
  }
}
```

Legado replaces `{{key}}` and `{{page}}` with user input, and resolves `SERVER` from
the book source URL. JSONPath rules (`$.items[*]`, `$.title`, etc.) map API response
fields to Legado's internal book model.

### 14.2 POST /api/legado/search

Body: `key=search-term&page=1`

Response:
```json
{
  "items": [
    {"book_id": 1, "title": "书名", "author": "作者", "chapter_count": 120, "latest_read_at": null}
  ]
}
```

Backend: queries `books` table with `LIKE` on title/author, same as `/api/mobile/books?q=...`.

### 14.3 GET /api/legado/book-info?url=BOOK_ID

Response:
```json
{
  "book_id": 1,
  "title": "书名",
  "author": "作者",
  "chapter_count": 120,
  "description": "120章 · 85分",
  "latest_read_at": null
}
```

### 14.4 GET /api/legado/toc?url=BOOK_ID

Response:
```json
{
  "book_id": 1,
  "chapters": [
    {"index": 0, "title": "第一章", "char_count": 3456},
    {"index": 1, "title": "第二章", "char_count": 2890}
  ]
}
```

### 14.5 GET /api/legado/content?url=BOOK_ID&index=CHAPTER_INDEX

Response (raw text, not JSON wrapper — Legado's ruleContent extracts `$.content` from JSON,
or returns the full response body as content if no JSONPath match):

```json
{
  "book_id": 1,
  "chapter_index": 0,
  "title": "第一章",
  "content": "第一章的全部正文内容...",
  "encoding": "utf-8"
}
```

Backend: same as `/api/mobile/books/{id}/chapters/{idx}`.

### 14.6 Implementation plan

All endpoints are thin wrappers around existing `mobile_service.py` functions:

| New endpoint | Maps to |
|-------------|---------|
| `/api/legado/search` | `get_mobile_books(repo, q=key)` + format as search result |
| `/api/legado/book-info` | `get_mobile_books(repo)` filtered to one book |
| `/api/legado/toc` | `get_mobile_chapters(repo, book_id)` |
| `/api/legado/content` | `get_mobile_chapter_content(repo, book_id, chapter_index)` |
| `/api/legado/source` | Static JSON with `SERVER` placeholder (replaced at runtime by Legado) |

Estimated effort: 1-2 hours.

## 15. Next executable tasks

1. User builds Legado to verify environment
2. Create NovelHub BookSource JSON
3. Add `/api/legado/source` to NovelHub
4. Test import + reading in Legado
5. Evaluate experience vs current android_app
6. Decide Approach A or B
