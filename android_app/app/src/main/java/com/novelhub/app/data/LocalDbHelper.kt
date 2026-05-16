package com.novelhub.app.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

class LocalDbHelper(ctx: Context) : SQLiteOpenHelper(ctx, DB_NAME, null, DB_VERSION) {
    companion object { const val DB_NAME = "novelhub_cache"; const val DB_VERSION = 1 }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE books(book_id INTEGER PRIMARY KEY, title TEXT, author TEXT, chapter_count INTEGER, progress_ratio REAL, latest_read_at TEXT, updated_at TEXT)")
        db.execSQL("CREATE TABLE chapters(book_id INTEGER, chapter_index INTEGER, title TEXT, cached INTEGER DEFAULT 0, PRIMARY KEY(book_id, chapter_index))")
        db.execSQL("CREATE TABLE chapter_contents(book_id INTEGER, chapter_index INTEGER, title TEXT, content TEXT, encoding TEXT, cached_at TEXT, PRIMARY KEY(book_id, chapter_index))")
        db.execSQL("CREATE TABLE progress(book_id INTEGER PRIMARY KEY, chapter_index INTEGER, chapter_scroll REAL, progress_ratio REAL, updated_at TEXT, pending_upload INTEGER)")
        db.execSQL("CREATE TABLE pending_progress(book_id INTEGER PRIMARY KEY, chapter_index INTEGER, progress_ratio REAL, updated_at TEXT)")
    }
    override fun onUpgrade(db: SQLiteDatabase?, old: Int, new: Int) {}

    fun upsertBooks(books: List<Book>) { writableDatabase.use { db -> db.beginTransaction(); try { db.delete("books",null,null); for (b in books) { val cv = ContentValues().apply { put("book_id",b.id); put("title",b.title); put("author",b.author); put("chapter_count",b.chapterCount); put("progress_ratio",b.progressRatio); put("latest_read_at",b.latestReadAt) }; db.insertWithOnConflict("books",null,cv,SQLiteDatabase.CONFLICT_REPLACE) }; db.setTransactionSuccessful() } finally { db.endTransaction() } } }

    fun getAllBooks(): List<Book> = readableDatabase.rawQuery("SELECT book_id,title,author,chapter_count,progress_ratio,latest_read_at FROM books ORDER BY CASE WHEN latest_read_at IS NULL THEN 1 ELSE 0 END, latest_read_at DESC",null).use { c -> val list = mutableListOf<Book>(); while (c.moveToNext()) list.add(Book(c.getLong(0),c.getString(1),c.getString(2),c.getInt(3),null,c.getString(5),c.getDouble(4))); list }

    fun cacheChapters(bookId: Long, chapters: List<ChapterItem>) { writableDatabase.use { db -> db.beginTransaction(); try { for (ch in chapters) { val cv = ContentValues().apply { put("book_id",bookId); put("chapter_index",ch.index); put("title",ch.title) }; db.insertWithOnConflict("chapters",null,cv,SQLiteDatabase.CONFLICT_REPLACE) }; db.setTransactionSuccessful() } finally { db.endTransaction() } } }

    fun getChapters(bookId: Long): List<ChapterItem> = readableDatabase.rawQuery("SELECT chapter_index,title FROM chapters WHERE book_id=? ORDER BY chapter_index", arrayOf(bookId.toString())).use { c -> val list = mutableListOf<ChapterItem>(); while (c.moveToNext()) list.add(ChapterItem(c.getInt(0),c.getString(1),0)); list }

    fun cacheChapterContent(bookId: Long, ch: ChapterContent) { val cv = ContentValues().apply { put("book_id",bookId); put("chapter_index",ch.chapterIndex); put("title",ch.title); put("content",ch.content); put("encoding",ch.encoding); put("cached_at",System.currentTimeMillis().toString()) }; writableDatabase.insertWithOnConflict("chapter_contents",null,cv,SQLiteDatabase.CONFLICT_REPLACE) }

    fun getChapterContent(bookId: Long, chapterIndex: Int): ChapterContent? = readableDatabase.rawQuery("SELECT title,content,encoding FROM chapter_contents WHERE book_id=? AND chapter_index=?", arrayOf(bookId.toString(),chapterIndex.toString())).use { c -> if (c.moveToFirst()) ChapterContent(bookId,chapterIndex,c.getString(0),c.getString(1),c.getString(2),null,null,0) else null }

    fun saveProgress(bookId: Long, chapterIndex: Int, progressRatio: Double) { val cv = ContentValues().apply { put("book_id",bookId); put("chapter_index",chapterIndex); put("progress_ratio",progressRatio); put("updated_at",System.currentTimeMillis().toString()) }; writableDatabase.insertWithOnConflict("progress",null,cv,SQLiteDatabase.CONFLICT_REPLACE) }

    fun getProgress(bookId: Long): Pair<Int,Double>? = readableDatabase.rawQuery("SELECT chapter_index,progress_ratio FROM progress WHERE book_id=?", arrayOf(bookId.toString())).use { c -> if (c.moveToFirst()) Pair(c.getInt(0),c.getDouble(1)) else null }

    fun queuePendingProgress(bookId: Long, chapterIndex: Int, ratio: Double) { val cv = ContentValues().apply { put("book_id",bookId); put("chapter_index",chapterIndex); put("progress_ratio",ratio); put("updated_at",System.currentTimeMillis().toString()) }; writableDatabase.insertWithOnConflict("pending_progress",null,cv,SQLiteDatabase.CONFLICT_REPLACE) }
    fun getPendingProgress(): List<Triple<Long,Int,Double>> = readableDatabase.rawQuery("SELECT book_id,chapter_index,progress_ratio FROM pending_progress",null).use { c -> val list = mutableListOf<Triple<Long,Int,Double>>(); while (c.moveToNext()) list.add(Triple(c.getLong(0),c.getInt(1),c.getDouble(2))); list }
    fun clearPendingProgress() { writableDatabase.delete("pending_progress",null,null) }
}
