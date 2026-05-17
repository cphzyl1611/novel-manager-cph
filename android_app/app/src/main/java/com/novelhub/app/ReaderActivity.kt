package com.novelhub.app

import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
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
import java.io.PrintWriter
import java.io.StringWriter
import java.util.concurrent.Executors

class ReaderActivity : AppCompatActivity() {
    companion object {
        private const val TAG = "NovelHub"
        private const val SWIPE_THRESHOLD = 80f
        private const val CHARS_PER_PAGE = 1000
        fun paginateText(content: String, charsPerPage: Int): List<String> {
            if (content.isEmpty()) return emptyList()
            val result = mutableListOf<String>()
            var pos = 0
            while (pos < content.length) {
                var end = (pos + charsPerPage).coerceAtMost(content.length)
                if (end < content.length) {
                    val lookahead = content.substring(end, (end + 200).coerceAtMost(content.length))
                    val dnl = lookahead.indexOf("\n\n"); if (dnl >= 0) end += dnl + 2
                    else {
                        val period = lookahead.indexOf("。"); if (period >= 0) end += period + 1
                        else { val nl = lookahead.indexOf("\n"); if (nl >= 0) end += nl + 1 }
                    }
                    end = end.coerceAtMost(content.length)
                }
                result.add(content.substring(pos, end)); pos = end
            }
            return result
        }
    }

    private lateinit var db: LocalDbHelper
    private lateinit var topBar: LinearLayout
    private lateinit var bottomBar: LinearLayout
    private lateinit var contentView: TextView
    private lateinit var titleView: TextView
    private lateinit var pageLabel: TextView
    private var bookId: Long = 0L; private var bookTitle: String = ""
    private var chapterIndex: Int = 0; private var pageIndex: Int = 0
    private var totalChapters: Int = 0
    private var pages: List<String> = emptyList(); private var curContent: String = ""
    private var controlsVisible: Boolean = true
    private val executor = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())
    private var touchDownX = 0f; private var touchDownY = 0f

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        bookId = intent.getLongExtra("book_id", 0L)
        bookTitle = intent.getStringExtra("title") ?: ""
        db = LocalDbHelper(this)

        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

        // Top bar
        topBar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setBackgroundColor(Color.argb(240, 255, 255, 255)); setPadding(8, 24, 8, 8); gravity = Gravity.CENTER_VERTICAL }
        topBar.addView(Button(this).apply { text = "←"; setOnClickListener { finish() } })
        titleView = TextView(this).apply { text = bookTitle; textSize = 16f; setTypeface(null, Typeface.BOLD); setPadding(16, 0, 16, 0) }
        topBar.addView(titleView, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        root.addView(topBar)

        // Content
        contentView = TextView(this).apply { textSize = 20f; setLineSpacing(6f, 1.2f); setPadding(24, 16, 24, 16); setTextColor(0xFF2C2C2C.toInt()) }
        root.addView(contentView, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))

        // Tap zone + swipe detection
        contentView.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> { touchDownX = event.x; touchDownY = event.y; true }
                MotionEvent.ACTION_UP -> {
                    val dx = event.x - touchDownX; val dy = event.y - touchDownY
                    if (Math.abs(dx) > SWIPE_THRESHOLD || Math.abs(dy) > SWIPE_THRESHOLD) {
                        if (dx < -SWIPE_THRESHOLD) nextPage() else if (dx > SWIPE_THRESHOLD) prevPage()
                    } else {
                        val w = contentView.width.toFloat()
                        if (event.x < w * 0.33f) prevPage() else if (event.x > w * 0.67f) nextPage() else toggleControls()
                    }
                    true
                }
                else -> false
            }
        }

        // Bottom bar
        bottomBar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER; setBackgroundColor(Color.argb(240, 255, 255, 255)); setPadding(8, 8, 8, 16) }
        pageLabel = TextView(this).apply { setPadding(8, 0, 8, 0); textSize = 13f }
        bottomBar.addView(Button(this).apply { text = getString(R.string.prev_page); setOnClickListener { prevPage() } })
        bottomBar.addView(pageLabel)
        bottomBar.addView(Button(this).apply { text = getString(R.string.next_page); setOnClickListener { nextPage() } })
        bottomBar.addView(Button(this).apply { text = getString(R.string.toc); setOnClickListener { showToc() } })
        root.addView(bottomBar)
        setContentView(root)

        val prog = db.getProgress(bookId)
        if (prog != null) { chapterIndex = prog.first.coerceIn(0, Int.MAX_VALUE); pageIndex = prog.second.coerceAtLeast(0) }
        loadChapter()
    }

    private fun safeUi(action: () -> Unit) {
        if (!isFinishing && !isDestroyed) runOnUiThread { try { action() } catch (e: Exception) { Log.e(TAG, "safeUi error", e) } }
    }

    private fun logCrash(e: Exception, ctx: String) {
        val sw = StringWriter(); e.printStackTrace(PrintWriter(sw))
        val prefs = getSharedPreferences("novelhub", MODE_PRIVATE)
        prefs.edit().putString("last_crash_type", e.javaClass.simpleName).putString("last_crash_msg", e.message ?: "").putString("last_crash_trace", sw.toString().take(2000)).putString("last_crash_time", java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss", java.util.Locale.getDefault()).format(java.util.Date())).putString("last_crash_ctx", ctx).putLong("last_crash_book_id", bookId).putInt("last_crash_ch", chapterIndex).putInt("last_crash_pg", pageIndex).apply()
        Log.e(TAG, "Crash in $ctx", e)
    }

    private fun loadChapter() {
        contentView.text = getString(R.string.loading)
        executor.execute {
            try {
                var ch = db.getChapterContent(bookId, chapterIndex)
                if (ch == null) { val r = ApiClient.fetchChapterContent(bookId, chapterIndex); if (r != null) { db.cacheChapterContent(bookId, r); ch = r } }
                if (ch != null && ch.content.isNotEmpty()) {
                    curContent = ch.content; totalChapters = ch.totalChapters.coerceAtLeast(1)
                    titleView.text = ch.title.ifEmpty { bookTitle }
                    pages = paginateText(curContent, CHARS_PER_PAGE)
                    pageIndex = pageIndex.coerceIn(0, (pages.size - 1).coerceAtLeast(0))
                    val joined = pages.joinToString("")
                    Log.d(TAG, "ch=$chapterIndex content=${ch.content.length} pages=${pages.size} joined=${joined.length} match=${joined == curContent}")
                    safeUi { displayPage() }
                } else { curContent = ""; pages = emptyList(); pageIndex = 0; safeUi { contentView.text = getString(R.string.empty_content); pageLabel.text = "0/0" } }
            } catch (e: Exception) { logCrash(e, "loadChapter: book=$bookId ch=$chapterIndex"); safeUi { contentView.text = getString(R.string.load_failed) } }
        }
    }

    private fun displayPage() {
        if (pages.isEmpty()) { contentView.text = getString(R.string.empty_content); pageLabel.text = "0/0"; return }
        contentView.text = pages[pageIndex.coerceIn(0, pages.size - 1)]
        pageLabel.text = (pageIndex + 1).toString() + "/" + pages.size; saveProgress()
    }

    private fun nextPage() {
        if (pages.isEmpty()) return
        if (pageIndex < pages.size - 1) { pageIndex++; displayPage() }
        else if (chapterIndex + 1 < totalChapters) { chapterIndex++; pageIndex = 0; loadChapter() }
    }

    private fun prevPage() {
        if (pages.isEmpty()) return
        if (pageIndex > 0) { pageIndex--; displayPage() }
        else if (chapterIndex > 0) { chapterIndex--; pageIndex = 0; loadChapter() }
    }

    private fun toggleControls() { controlsVisible = !controlsVisible; val v = if (controlsVisible) View.VISIBLE else View.GONE; topBar.visibility = v; bottomBar.visibility = v }

    private fun showToc() {
        executor.execute {
            try {
                var lc = db.getChapters(bookId)
                if (lc.isEmpty()) { val r = ApiClient.fetchChapters(bookId); if (r.chapters.isNotEmpty()) { db.cacheChapters(bookId, r.chapters); lc = r.chapters } }
                val titles = lc.map { it.title }.toTypedArray()
                if (titles.isEmpty()) { safeUi { Toast.makeText(this@ReaderActivity, getString(R.string.no_chapters), Toast.LENGTH_SHORT).show() }; return@execute }
                safeUi { if (!isFinishing && !isDestroyed) AlertDialog.Builder(this@ReaderActivity).setTitle(getString(R.string.toc)).setItems(titles) { _, i -> chapterIndex = i; pageIndex = 0; loadChapter() }.show() }
            } catch (e: Exception) { logCrash(e, "showToc: book=$bookId") }
        }
    }

    private fun saveProgress() {
        val sc = chapterIndex.coerceIn(0, (totalChapters - 1).coerceAtLeast(0)); val sp = pages.size.coerceAtLeast(1)
        val ratio = (sc.toDouble() + pageIndex.coerceAtLeast(0).toDouble() / sp) / totalChapters.coerceAtLeast(1)
        executor.execute { try { db.saveProgress(bookId, sc, pageIndex, ratio.coerceIn(0.0, 1.0)); if (ApiClient.hasServerUrl()) ApiClient.postProgress(bookId, sc, ratio, pageIndex, "android") } catch (e: Exception) { logCrash(e, "saveProgress") } }
    }
}
