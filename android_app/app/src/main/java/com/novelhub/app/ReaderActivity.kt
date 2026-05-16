package com.novelhub.app

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.novelhub.app.data.ApiClient
import com.novelhub.app.data.ChapterContent
import com.novelhub.app.data.ChapterItem
import com.novelhub.app.data.LocalDbHelper
import java.util.concurrent.Executors

class ReaderActivity : AppCompatActivity() {
    private lateinit var db: LocalDbHelper
    private lateinit var contentView: TextView
    private lateinit var scrollView: ScrollView
    private var bookId: Long = 0
    private var bookTitle: String = ""
    private var chapterIndex: Int = 0
    private var chapters: List<ChapterItem> = emptyList()
    private var totalChapters: Int = 0
    private val executor = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        bookId = intent.getLongExtra("book_id", 0)
        bookTitle = intent.getStringExtra("title") ?: ""
        db = LocalDbHelper(this)

        // Build a simple TextView + ScrollView reader
        scrollView = ScrollView(this)
        contentView = TextView(this).apply {
            textSize = 18f; setLineSpacing(4f, 1f)
            setPadding(32, 32, 32, 32); setTextColor(0xFF2C2C2C.toInt())
        }
        scrollView.addView(contentView)
        setContentView(scrollView)

        title = bookTitle
        loadChapter()
    }

    private fun loadChapter() {
        contentView.text = "Loading..."
        executor.execute {
            // Try cached first
            val cached = db.getChapterContent(bookId, chapterIndex)
            if (cached != null) {
                handler.post { displayChapter(cached) }
                return@execute
            }
            // Fetch chapters list if needed
            if (chapters.isEmpty()) {
                val resp = ApiClient.fetchChapters(bookId)
                chapters = resp.chapters
                db.cacheChapters(bookId, chapters)
            }
            // Fetch single chapter
            val ch = ApiClient.fetchChapterContent(bookId, chapterIndex)
            if (ch != null) {
                db.cacheChapterContent(bookId, ch)
                handler.post { displayChapter(ch) }
            } else {
                handler.post { contentView.text = "Failed to load chapter." }
            }
        }
        // Preload next chapter
        executor.execute {
            val nextCh = ApiClient.fetchChapterContent(bookId, chapterIndex + 1)
            if (nextCh != null) db.cacheChapterContent(bookId, nextCh)
        }
    }

    private fun displayChapter(ch: ChapterContent) {
        title = ch.title.ifEmpty { bookTitle }
        contentView.text = ch.content
        scrollView.scrollTo(0, 0)
        totalChapters = ch.totalChapters
        // Save progress
        db.saveProgress(bookId, chapterIndex, 0.0)
        // Upload progress
        executor.execute { ApiClient.postProgress(bookId, chapterIndex, 0.0, "android") }
    }

    override fun onBackPressed() {
        if (chapterIndex > 0) { chapterIndex--; loadChapter() }
        else super.onBackPressed()
    }

    // Called from options menu
    fun nextChapter() { if (chapterIndex + 1 < totalChapters) { chapterIndex++; loadChapter() } }
    fun prevChapter() { if (chapterIndex > 0) { chapterIndex--; loadChapter() } }
    fun showToc() {
        if (chapters.isEmpty()) { Toast.makeText(this, "No chapters", Toast.LENGTH_SHORT).show(); return }
        val titles = chapters.map { it.title }.toTypedArray()
        AlertDialog.Builder(this).setTitle("Chapters").setItems(titles) { _, i -> chapterIndex = i; loadChapter() }.show()
    }
    fun changeFontSize(delta: Int) { contentView.textSize = (contentView.textSize + delta).coerceIn(12f, 32f) }
}
