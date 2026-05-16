package com.novelhub.app

import android.content.Intent
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.novelhub.app.data.ApiClient
import com.novelhub.app.data.Book
import com.novelhub.app.data.LocalDbHelper
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {
    private lateinit var db: LocalDbHelper
    private lateinit var shelfLayout: LinearLayout
    private var books: List<Book> = emptyList()
    private val executor = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        db = LocalDbHelper(this)
        ApiClient.init(this)
        title = getString(R.string.app_name)

        val scroll = ScrollView(this)
        shelfLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(16, 16, 16, 16)
        }
        scroll.addView(shelfLayout)
        setContentView(scroll)
        loadLocalShelf()
    }

    private fun loadLocalShelf() {
        shelfLayout.removeAllViews()
        val toolbar = createToolbar()
        shelfLayout.addView(toolbar)
        executor.execute {
            books = db.getAllBooks()
            runOnUiThread { renderShelfInner() }
        }
    }

    private fun createToolbar(): LinearLayout {
        val t = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(0, 0, 0, 12) }
        t.addView(Button(this).apply { text = getString(R.string.sync); setOnClickListener { doSync() } })
        t.addView(Button(this).apply { text = getString(R.string.server_config); setOnClickListener { startActivity(Intent(this@MainActivity, ServerConfigActivity::class.java)) } })
        return t
    }

    private fun renderShelfInner() {
        shelfLayout.removeAllViews()
        shelfLayout.addView(createToolbar())

        if (books.isEmpty()) {
            shelfLayout.addView(TextView(this).apply {
                text = getString(R.string.no_books) + "\n" + getString(R.string.tap_sync)
                setPadding(16, 48, 16, 16); textSize = 15f
            })
        } else {
            for (b in books) {
                val info = b.title + "\n" + b.author + " | " + b.chapterCount + "章"
                val card = TextView(this).apply {
                    text = info; setPadding(16, 14, 16, 14); textSize = 16f
                    setBackgroundColor(0xFFFFFFFF.toInt())
                    setOnClickListener {
                        val intent = Intent(this@MainActivity, ReaderActivity::class.java)
                        intent.putExtra("book_id", b.id)
                        intent.putExtra("title", b.title)
                        startActivity(intent)
                    }
                }
                val params = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { setMargins(0, 0, 0, 8) }
                shelfLayout.addView(card, params)
            }
        }
    }

    private fun doSync() {
        if (!ApiClient.hasServerUrl()) {
            Toast.makeText(this, getString(R.string.set_server_first), Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, ServerConfigActivity::class.java))
            return
        }
        Toast.makeText(this, getString(R.string.syncing), Toast.LENGTH_SHORT).show()
        executor.execute {
            val resp = ApiClient.fetchBooks()
            if (resp.items.isNotEmpty()) {
                db.upsertBooks(resp.items)
                books = db.getAllBooks()
                runOnUiThread {
                    renderShelfInner()
                    Toast.makeText(this@MainActivity, getString(R.string.books_synced).format(resp.items.size), Toast.LENGTH_SHORT).show()
                }
            } else {
                runOnUiThread { Toast.makeText(this@MainActivity, getString(R.string.sync_failed), Toast.LENGTH_SHORT).show() }
            }
        }
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 1, 0, getString(R.string.sync))
        menu.add(0, 2, 0, getString(R.string.server_config))
        menu.add(0, 3, 0, getString(R.string.clear_cache))
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            1 -> doSync()
            2 -> startActivity(Intent(this, ServerConfigActivity::class.java))
            3 -> {
                db.clearCache(); loadLocalShelf()
                Toast.makeText(this, getString(R.string.cache_cleared), Toast.LENGTH_SHORT).show()
            }
        }
        return true
    }
}
