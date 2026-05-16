package com.novelhub.app

import android.graphics.Typeface
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
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
    private lateinit var titleView: TextView
    private lateinit var pageLabel: TextView
    private var bookId: Long = 0L
    private var bookTitle: String = ""
    private var chapterIndex: Int = 0
    private var pageIndex: Int = 0
    private var totalChapters: Int = 0
    private var pages: List<String> = emptyList()
    private var curContent: String = ""
    private val executor = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())
    private val charsPerPage = 1000

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        bookId = intent.getLongExtra("book_id", 0L)
        bookTitle = intent.getStringExtra("title") ?: ""
        db = LocalDbHelper(this)

        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        titleView = TextView(this).apply { text = bookTitle; textSize = 18f; setTypeface(null, Typeface.BOLD); setPadding(16, 16, 16, 8); gravity = Gravity.CENTER }
        root.addView(titleView)
        contentView = TextView(this).apply { textSize = 20f; setLineSpacing(6f, 1.2f); setPadding(24, 16, 24, 16); setTextColor(0xFF2C2C2C.toInt()) }
        root.addView(contentView, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))

        val bar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER; setPadding(8, 8, 8, 8) }
        pageLabel = TextView(this).apply { setPadding(8, 0, 8, 0); textSize = 13f }
        bar.addView(Button(this).apply { text = getString(R.string.prev_page); setOnClickListener { prevPage() } })
        bar.addView(pageLabel)
        bar.addView(Button(this).apply { text = getString(R.string.next_page); setOnClickListener { nextPage() } })
        bar.addView(Button(this).apply { text = getString(R.string.toc); setOnClickListener { showToc() } })
        root.addView(bar)
        setContentView(root)

        val prog = db.getProgress(bookId)
        if (prog != null) { chapterIndex = prog.first.coerceIn(0, Int.MAX_VALUE); pageIndex = prog.second.coerceAtLeast(0) }
        loadChapter()
    }

    private fun loadChapter() {
        contentView.text = getString(R.string.loading)
        executor.execute {
            var ch = db.getChapterContent(bookId, chapterIndex)
            if (ch == null) {
                val r = ApiClient.fetchChapterContent(bookId, chapterIndex)
                if (r != null) { db.cacheChapterContent(bookId, r); ch = r }
            }
            if (ch != null && ch.content.isNotEmpty()) {
                curContent = ch.content; totalChapters = ch.totalChapters.coerceAtLeast(1)
                titleView.text = ch.title.ifEmpty { bookTitle }
                pages = paginateText(curContent, charsPerPage)
                pageIndex = pageIndex.coerceIn(0, (pages.size - 1).coerceAtLeast(0))
                handler.post { displayPage() }
            } else {
                curContent = ""; pages = emptyList(); pageIndex = 0
                handler.post { contentView.text = getString(R.string.empty_content); pageLabel.text = "0/0" }
            }
        }
    }

    private fun displayPage() {
        if (pages.isEmpty()) { contentView.text = getString(R.string.empty_content); pageLabel.text = "0/0"; return }
        contentView.text = pages[pageIndex.coerceIn(0, pages.size - 1)]
        pageLabel.text = (pageIndex + 1).toString() + "/" + pages.size
        saveProgress()
    }

    private fun nextPage() {
        if (pages.isEmpty()) return
        if (pageIndex < pages.size - 1) { pageIndex++; displayPage() }
        else if (chapterIndex + 1 < totalChapters) { chapterIndex++; pageIndex = 0; loadChapter() }
    }

    private fun prevPage() {
        if (pages.isEmpty()) return
        if (pageIndex > 0) { pageIndex--; displayPage() }
        else if (chapterIndex > 0) { chapterIndex--; pageIndex = Int.MAX_VALUE; loadChapter() }
    }

    private fun showToc() {
        executor.execute {
            var localChs = db.getChapters(bookId)
            if (localChs.isEmpty()) {
                val r = ApiClient.fetchChapters(bookId)
                if (r.chapters.isNotEmpty()) { db.cacheChapters(bookId, r.chapters); localChs = r.chapters }
            }
            val titles = localChs.map { it.title }.toTypedArray()
            if (titles.isEmpty()) {
                handler.post { Toast.makeText(this@ReaderActivity, getString(R.string.no_chapters), Toast.LENGTH_SHORT).show() }
                return@execute
            }
            handler.post {
                AlertDialog.Builder(this@ReaderActivity)
                    .setTitle(getString(R.string.toc))
                    .setItems(titles) { _, i -> chapterIndex = i; pageIndex = 0; loadChapter() }
                    .show()
            }
        }
    }

    private fun saveProgress() {
        val safeChapterIndex = chapterIndex.coerceIn(0, (totalChapters - 1).coerceAtLeast(0))
        val safePages = pages.size.coerceAtLeast(1)
        val ratio = (safeChapterIndex.toDouble() + pageIndex.coerceAtLeast(0).toDouble() / safePages) / totalChapters.coerceAtLeast(1)
        executor.execute {
            db.saveProgress(bookId, safeChapterIndex, pageIndex, ratio.coerceIn(0.0, 1.0))
            if (ApiClient.hasServerUrl()) { ApiClient.postProgress(bookId, safeChapterIndex, ratio, pageIndex, "android") }
        }
    }

    companion object {
        fun paginateText(content: String, charsPerPage: Int): List<String> {
            if (content.isEmpty()) return emptyList()
            val result = mutableListOf<String>()
            var pos = 0
            while (pos < content.length) {
                var end = (pos + charsPerPage).coerceAtMost(content.length)
                if (end < content.length) {
                    val lookahead = content.substring(end, (end + 200).coerceAtMost(content.length))
                    val dnl = lookahead.indexOf("\n\n")
                    if (dnl >= 0) end += dnl + 2
                    else {
                        val period = lookahead.indexOf("。")
                        if (period >= 0) end += period + 1
                        else {
                            val nl = lookahead.indexOf("\n")
                            if (nl >= 0) end += nl + 1
                        }
                    }
                    end = end.coerceAtMost(content.length)
                }
                result.add(content.substring(pos, end)); pos = end
            }
            return result
        }
    }
}
