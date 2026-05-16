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
        ApiClient.init(this)
        title = "NovelHub"

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

        // Toolbar: Sync + Server buttons
        val toolbar = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(0, 0, 0, 12) }
        toolbar.addView(Button(this).apply { text = "Sync"; setOnClickListener { doSync() } })
        toolbar.addView(Button(this).apply {
            text = "Server"
            setOnClickListener { startActivity(Intent(this@MainActivity, ServerConfigActivity::class.java)) }
        })
        shelfLayout.addView(toolbar)

        executor.execute {
            books = db.getAllBooks()
            runOnUiThread { renderShelf(toolbar) }
        }
    }

    private fun renderShelf(toolbar: LinearLayout) {
        shelfLayout.removeAllViews()
        shelfLayout.addView(toolbar)

        if (books.isEmpty()) {
            val tv = TextView(this).apply {
                text = "No books yet." + "\n" + "Tap Sync to connect to your PC server."
                setPadding(16, 48, 16, 16)
                textSize = 15f
            }
            shelfLayout.addView(tv)
        } else {
            for (b in books) {
                val info = b.title + "\n" + b.author + " | " + b.chapterCount + " ch"
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
                )
                params.setMargins(0, 0, 0, 8)
                shelfLayout.addView(card, params)
            }
        }
    }

    private fun doSync() {
        if (!ApiClient.hasServerUrl()) {
            Toast.makeText(this, "Set server address first", Toast.LENGTH_SHORT).show()
            startActivity(Intent(this, ServerConfigActivity::class.java))
            return
        }
        Toast.makeText(this, "Syncing...", Toast.LENGTH_SHORT).show()
        executor.execute {
            val resp = ApiClient.fetchBooks()
            if (resp.items.isNotEmpty()) {
                db.upsertBooks(resp.items)
                books = db.getAllBooks()
                runOnUiThread { renderShelf(shelfLayout.getChildAt(0) as LinearLayout) }
                runOnUiThread { Toast.makeText(this, resp.items.size.toString() + " books synced", Toast.LENGTH_SHORT).show() }
            } else {
                runOnUiThread { Toast.makeText(this, "Sync failed or no books", Toast.LENGTH_SHORT).show() }
            }
        }
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 1, 0, "Sync")
        menu.add(0, 2, 0, "Server Config")
        menu.add(0, 3, 0, "Clear Cache")
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            1 -> doSync()
            2 -> startActivity(Intent(this, ServerConfigActivity::class.java))
            3 -> { db.clearCache(); loadLocalShelf(); Toast.makeText(this, "Cache cleared", Toast.LENGTH_SHORT).show() }
        }
        return true
    }
}
