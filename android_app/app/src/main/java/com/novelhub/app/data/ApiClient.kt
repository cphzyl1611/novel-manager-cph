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
    private var baseUrl = ""
    private var prefs: SharedPreferences? = null

    fun init(ctx: Context) { prefs = ctx.getSharedPreferences("novelhub", Context.MODE_PRIVATE); baseUrl = prefs?.getString("server_url","") ?: "" }
    fun setServerUrl(url: String) { baseUrl = url.trimEnd('/'); prefs?.edit()?.putString("server_url",baseUrl)?.apply() }
    fun getServerUrl() = baseUrl

    private fun httpGet(path: String): String? {
        if (baseUrl.isEmpty()) return null
        return try {
            val c = URL(baseUrl+path).openConnection() as HttpURLConnection
            c.connectTimeout = 10000; c.readTimeout = 30000
            c.setRequestProperty("Accept","application/json")
            if (c.responseCode != 200) return null
            BufferedReader(InputStreamReader(c.inputStream)).readText()
        } catch (e: Exception) { null }
    }

    fun fetchBooks(): BooksResponse {
        val items = mutableListOf<Book>(); var rev = 0L
        val json = httpGet("/api/mobile/books")
        if (json != null) { val o = JSONObject(json); rev = o.optLong("server_revision",0); val a = o.optJSONArray("items")?:JSONArray()
            for (i in 0 until a.length()) { val b = a.getJSONObject(i); items.add(Book(b.getLong("book_id"),b.optString("title"),b.optString("author"),b.optInt("chapter_count"),if(b.isNull("quality_score"))null else b.getDouble("quality_score"),b.optString("latest_read_at",null),b.optDouble("progress_ratio",0.0))) } }
        return BooksResponse(items, rev)
    }

    fun fetchChapters(bookId: Long): ChaptersResponse {
        val json = httpGet("/api/mobile/books/$bookId/chapters") ?: return ChaptersResponse(bookId,"",emptyList(),null)
        val o = JSONObject(json); val list = mutableListOf<ChapterItem>(); val a = o.optJSONArray("chapters")?:JSONArray()
        for (i in 0 until a.length()) { val c = a.getJSONObject(i); list.add(ChapterItem(c.getInt("index"),c.optString("title"),c.optInt("char_count"))) }
        return ChaptersResponse(bookId, o.optString("title"), list, o.optString("note",null))
    }

    fun fetchChapterContent(bookId: Long, chapterIndex: Int): ChapterContent? {
        val json = httpGet("/api/mobile/books/$bookId/chapters/$chapterIndex") ?: return null
        val o = JSONObject(json)
        return ChapterContent(o.getLong("book_id"),o.getInt("chapter_index"),o.optString("title"),o.optString("content"),o.optString("encoding"),if(o.isNull("prev"))null else o.getInt("prev"),if(o.isNull("next"))null else o.getInt("next"),o.optInt("total_chapters"))
    }

    fun postProgress(bookId: Long, chapterIndex: Int, progressRatio: Double, deviceId: String) {
        try {
            val json = JSONObject().apply { put("book_id",bookId); put("chapter_index",chapterIndex); put("progress_ratio",progressRatio); put("device_id",deviceId) }
            val c = URL(baseUrl+"/api/mobile/progress").openConnection() as HttpURLConnection
            c.connectTimeout = 10000; c.requestMethod = "POST"; c.doOutput = true
            c.setRequestProperty("Content-Type","application/json")
            OutputStreamWriter(c.outputStream).use { it.write(json.toString()) }
            c.responseCode
        } catch (_: Exception) {}
    }
}
