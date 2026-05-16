"""Fix Android reader v2: LocalFirst startup, paged reading, no truncation."""
import os

APP = r"E:\github\novel_repo_manager\android_app\app\src\main\java\com\novelhub\app"
DATA = os.path.join(APP, "data")

def w(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.lstrip("\n"))
    print(os.path.basename(path), "done")

# ============ LocalDbHelper.kt v2 ============
w(os.path.join(DATA, "LocalDbHelper.kt"), """
package com.novelhub.app.data
import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
class LocalDbHelper(ctx: Context) : SQLiteOpenHelper(ctx, DB_NAME, null, DB_VERSION) {
    companion object { const val DB_NAME = "novelhub_cache"; const val DB_VERSION = 2 }
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE books(book_id INTEGER PRIMARY KEY, title TEXT, author TEXT, chapter_count INTEGER, progress_ratio REAL, latest_read_at TEXT, updated_at TEXT)")
        db.execSQL("CREATE TABLE chapters(book_id INTEGER, chapter_index INTEGER, title TEXT, cached INTEGER DEFAULT 0, PRIMARY KEY(book_id, chapter_index))")
        db.execSQL("CREATE TABLE chapter_contents(book_id INTEGER, chapter_index INTEGER, title TEXT, content TEXT, encoding TEXT, cached_at TEXT, PRIMARY KEY(book_id, chapter_index))")
        db.execSQL("CREATE TABLE progress(book_id INTEGER PRIMARY KEY, chapter_index INTEGER, page_index INTEGER DEFAULT 0, progress_ratio REAL, updated_at TEXT, pending_upload INTEGER)")
        db.execSQL("CREATE TABLE sync_config(key TEXT PRIMARY KEY, value TEXT)")
    }
    override fun onUpgrade(db: SQLiteDatabase, old: Int, new: Int) {
        if (old < 2) { db.execSQL("CREATE TABLE IF NOT EXISTS sync_config(key TEXT PRIMARY KEY, value TEXT)"); try { db.execSQL("ALTER TABLE progress ADD COLUMN page_index INTEGER DEFAULT 0") } catch (_: Exception) {} }
    }
    fun upsertBooks(books: List<Book>) { val d = writableDatabase; d.beginTransaction(); try { d.delete("books",null,null); for (b in books) { val cv = ContentValues().apply { put("book_id",b.id); put("title",b.title); put("author",b.author); put("chapter_count",b.chapterCount); put("progress_ratio",b.progressRatio); put("latest_read_at",b.latestReadAt) }; d.insertWithOnConflict("books",null,cv,SQLiteDatabase.CONFLICT_REPLACE) }; d.setTransactionSuccessful() } finally { d.endTransaction() } }
    fun getAllBooks(): List<Book> = readableDatabase.rawQuery("SELECT book_id,title,author,chapter_count,progress_ratio,latest_read_at FROM books ORDER BY CASE WHEN latest_read_at IS NULL THEN 1 ELSE 0 END, latest_read_at DESC",null).use { c -> val list = mutableListOf<Book>(); while (c.moveToNext()) list.add(Book(c.getLong(0),c.getString(1),c.getString(2),c.getInt(3),null,c.getString(5),c.getDouble(4))); list }
    fun getBookCount(): Int = readableDatabase.rawQuery("SELECT COUNT(*) FROM books",null).use { it.moveToFirst(); it.getInt(0) }
    fun cacheChapters(bookId: Long, chs: List<ChapterItem>) { val d = writableDatabase; d.beginTransaction(); try { for (ch in chs) { val cv = ContentValues().apply { put("book_id",bookId); put("chapter_index",ch.index); put("title",ch.title) }; d.insertWithOnConflict("chapters",null,cv,SQLiteDatabase.CONFLICT_REPLACE) }; d.setTransactionSuccessful() } finally { d.endTransaction() } }
    fun getChapters(bookId: Long): List<ChapterItem> = readableDatabase.rawQuery("SELECT chapter_index,title FROM chapters WHERE book_id=? ORDER BY chapter_index", arrayOf(bookId.toString())).use { c -> val list = mutableListOf<ChapterItem>(); while (c.moveToNext()) list.add(ChapterItem(c.getInt(0),c.getString(1),0)); list }
    fun cacheChapterContent(bookId: Long, ch: ChapterContent) { val cv = ContentValues().apply { put("book_id",bookId); put("chapter_index",ch.chapterIndex); put("title",ch.title); put("content",ch.content); put("encoding",ch.encoding); put("cached_at",System.currentTimeMillis().toString()) }; writableDatabase.insertWithOnConflict("chapter_contents",null,cv,SQLiteDatabase.CONFLICT_REPLACE) }
    fun getChapterContent(bookId: Long, ci: Int): ChapterContent? = readableDatabase.rawQuery("SELECT title,content,encoding FROM chapter_contents WHERE book_id=? AND chapter_index=?", arrayOf(bookId.toString(),ci.toString())).use { c -> if (c.moveToFirst()) ChapterContent(bookId,ci,c.getString(0),c.getString(1),c.getString(2),null,null,0) else null }
    fun saveProgress(bookId: Long, ci: Int, pi: Int, ratio: Double) { val cv = ContentValues().apply { put("book_id",bookId); put("chapter_index",ci); put("page_index",pi); put("progress_ratio",ratio); put("pending_upload",0); put("updated_at",System.currentTimeMillis().toString()) }; writableDatabase.insertWithOnConflict("progress",null,cv,SQLiteDatabase.CONFLICT_REPLACE) }
    fun getProgress(bookId: Long): Triple<Int,Int,Double>? = readableDatabase.rawQuery("SELECT chapter_index,page_index,progress_ratio FROM progress WHERE book_id=?", arrayOf(bookId.toString())).use { c -> if (c.moveToFirst()) Triple(c.getInt(0),c.getInt(1),c.getDouble(2)) else null }
    fun getServerUrl(): String = try { readableDatabase.rawQuery("SELECT value FROM sync_config WHERE key='server_url'",null).use { c -> if (c.moveToFirst()) c.getString(0) ?: "" else "" } } catch (_: Exception) { "" }
    fun setServerUrl(url: String) { val cv = ContentValues().apply { put("key","server_url"); put("value",url) }; writableDatabase.insertWithOnConflict("sync_config",null,cv,SQLiteDatabase.CONFLICT_REPLACE) }
    fun clearCache() { writableDatabase.use { d -> d.execSQL("DELETE FROM books"); d.execSQL("DELETE FROM chapters"); d.execSQL("DELETE FROM chapter_contents") } }
}
""")

# ============ ApiClient.kt v2 ============
w(os.path.join(DATA, "ApiClient.kt"), r"""
package com.novelhub.app.data
import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
object ApiClient {
    private var baseUrl = ""; private var db: LocalDbHelper? = null; private var sp: SharedPreferences? = null
    fun init(ctx: Context) { db = LocalDbHelper(ctx); sp = ctx.getSharedPreferences("novelhub",Context.MODE_PRIVATE); baseUrl = db?.getServerUrl() ?: sp?.getString("server_url","") ?: "" }
    fun setServerUrl(url: String) { baseUrl = url.trimEnd('/'); db?.setServerUrl(baseUrl); sp?.edit()?.putString("server_url",baseUrl)?.apply() }
    fun getServerUrl() = baseUrl; fun hasServerUrl() = baseUrl.isNotEmpty()
    fun testConnection(): Boolean { if (baseUrl.isEmpty()) return false; return try { val c = URL(baseUrl+"/api/health").openConnection() as HttpURLConnection; c.connectTimeout=5000; c.readTimeout=5000; c.responseCode==200 } catch (_: Exception) { false } }
    private fun httpGet(path: String, timeout: Int=30000): String? { if (baseUrl.isEmpty()) return null; return try { val c = URL(baseUrl+path).openConnection() as HttpURLConnection; c.connectTimeout=10000; c.readTimeout=timeout; c.setRequestProperty("Accept","application/json"); if (c.responseCode!=200) return null; BufferedReader(InputStreamReader(c.inputStream)).readText() } catch (e: Exception) { null } }
    fun fetchBooks(): BooksResponse { val items = mutableListOf<Book>(); var rev=0L; val json=httpGet("/api/mobile/books"); if(json!=null){val o=JSONObject(json);rev=o.optLong("server_revision",0);val a=o.optJSONArray("items")?:JSONArray();for(i in 0 until a.length()){val b=a.getJSONObject(i);items.add(Book(b.getLong("book_id"),b.optString("title"),b.optString("author"),b.optInt("chapter_count"),if(b.isNull("quality_score"))null else b.getDouble("quality_score"),if(b.isNull("latest_read_at"))null else b.optString("latest_read_at"),b.optDouble("progress_ratio",0.0)))}};return BooksResponse(items,rev) }
    fun fetchChapters(bookId: Long): ChaptersResponse { val json=httpGet("/api/mobile/books/$bookId/chapters")?:return ChaptersResponse(bookId,"",emptyList(),null);val o=JSONObject(json);val list=mutableListOf<ChapterItem>();val a=o.optJSONArray("chapters")?:JSONArray();for(i in 0 until a.length()){val c=a.getJSONObject(i);list.add(ChapterItem(c.getInt("index"),c.optString("title"),c.optInt("char_count")))};return ChaptersResponse(bookId,o.optString("title"),list,o.optString("note",null)) }
    fun fetchChapterContent(bookId: Long, ci: Int): ChapterContent? { val json=httpGet("/api/mobile/books/$bookId/chapters/$ci",60000)?:return null;val o=JSONObject(json);return ChapterContent(o.getLong("book_id"),o.getInt("chapter_index"),o.optString("title"),o.optString("content"),o.optString("encoding"),if(o.isNull("prev"))null else o.getInt("prev"),if(o.isNull("next"))null else o.getInt("next"),o.optInt("total_chapters")) }
    fun postProgress(bookId: Long, ci: Int, ratio: Double, pi: Int, deviceId: String) { try { val json=JSONObject().apply{put("book_id",bookId);put("chapter_index",ci);put("progress_ratio",ratio);put("page_index",pi);put("device_id",deviceId)};val c=URL(baseUrl+"/api/mobile/progress").openConnection() as HttpURLConnection;c.connectTimeout=10000;c.requestMethod="POST";c.doOutput=true;c.setRequestProperty("Content-Type","application/json");OutputStreamWriter(c.outputStream).use{it.write(json.toString())};c.responseCode } catch (_: Exception) {} }
}
""")
