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
import androidx.appcompat.app.AlertDialog
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

        val scroll = ScrollView(this)
        shelfLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(16, 16, 16, 16)
        }
        scroll.addView(shelfLayout)
        setContentView(scroll)

        ApiClient.init(this)
        title = "NovelHub"

        val url = ApiClient.getServerUrl()
        if (url.isEmpty()) {
            startActivity(Intent(this, ServerConfigActivity::class.java))
            finish()
            return
        }
        loadShelf()
    }

    private fun loadShelf() {
        shelfLayout.removeAllViews()

        // Header buttons
        val toolbar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, 0, 0, 12)
        }
        val syncBtn = Button(this).apply {
            text = "Sync"
            setOnClickListener { loadShelf() }
        }
        val serverBtn = Button(this).apply {
            text = "Server"
            setOnClickListener {
                startActivity(Intent(this@MainActivity, ServerConfigActivity::class.java))
                finish()
            }
        }
        toolbar.addView(syncBtn)
        toolbar.addView(serverBtn)
        shelfLayout.addView(toolbar)

        val label = TextView(this).apply {
            text = "Loading..."
            setPadding(8, 16, 8, 8)
        }
        shelfLayout.addView(label)

        executor.execute {
            val resp = ApiClient.fetchBooks()
            if (resp.items.isNotEmpty()) {
                db.upsertBooks(resp.items)
            }
            val localBooks = db.getAllBooks()
            books = localBooks

            runOnUiThread {
                shelfLayout.removeAllViews()
                shelfLayout.addView(toolbar)

                if (books.isEmpty()) {
                    shelfLayout.addView(TextView(this).apply {
                        text = "No books. Tap Sync to connect to server."
                        setPadding(16, 48, 16, 16)
                    })
                } else {
                    for (b in books) {
                        val info = buildString {
                            append(b.title)
                            append("\n")
                            if (b.author.isNotEmpty()) {
                                append(b.author)
                                append(" | ")
                            }
                            append(b.chapterCount)
                            append(" ch")
                        }
                        val card = TextView(this).apply {
                            text = info
                            setPadding(16, 14, 16, 14)
                            textSize = 16f
                            setBackgroundColor(0xFFFFFFFF.toInt())
                            setOnClickListener { openBook(b) }
                        }
                        val params = LinearLayout.LayoutParams(
                            LinearLayout.LayoutParams.MATCH_PARENT,
                            LinearLayout.LayoutParams.WRAP_CONTENT
                        )
                        params.setMargins(0, 0, 0, 8)
                        shelfLayout.addView(card, params)
                    }
                }
            }
        }
    }

    private fun openBook(book: Book) {
        val intent = Intent(this, ReaderActivity::class.java).apply {
            putExtra("book_id", book.id)
            putExtra("title", book.title)
        }
        startActivity(intent)
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 1, 0, "Sync")
        menu.add(0, 2, 0, "Change Server")
        menu.add(0, 3, 0, "Clear Cache")
        menu.add(0, 4, 0, "About")
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            1 -> {
                Toast.makeText(this, "Syncing...", Toast.LENGTH_SHORT).show()
                loadShelf()
            }
            2 -> {
                startActivity(Intent(this, ServerConfigActivity::class.java))
                finish()
            }
            3 -> {
                deleteDatabase("novelhub_cache")
                db = LocalDbHelper(this)
                loadShelf()
                Toast.makeText(this, "Cache cleared", Toast.LENGTH_SHORT).show()
            }
            4 -> AlertDialog.Builder(this)
                .setTitle("NovelHub")
                .setMessage("Native Android Reader v1." + "\n" + "Connect to LAN server to sync.")
                .setPositiveButton("OK", null).show()
        }
        return true
    }
}
