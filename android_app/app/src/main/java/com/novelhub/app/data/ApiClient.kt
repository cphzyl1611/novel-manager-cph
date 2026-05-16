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
