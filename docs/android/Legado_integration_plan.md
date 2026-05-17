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
- **JDK**: NOT FOUND in current environment
- **Android SDK**: NOT SET
- **Build**: NOT attempted

Required: JDK 17+, Android SDK Platform 34+, Kotlin 1.9.22, AGP 8.2.2.

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

## 14. Next executable tasks

1. User builds Legado to verify environment
2. Create NovelHub BookSource JSON
3. Add `/api/legado/source` to NovelHub
4. Test import + reading in Legado
5. Evaluate experience vs current android_app
6. Decide Approach A or B
