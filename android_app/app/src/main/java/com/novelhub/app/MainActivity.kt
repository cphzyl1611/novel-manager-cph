package com.novelhub.app

import android.annotation.SuppressLint
import android.os.Bundle
import android.view.KeyEvent
import android.view.Menu
import android.view.MenuItem
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView
    private var serverUrl: String = ""

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        webView = findViewById(R.id.webView)
        configureWebView()
        loadServer()
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.menu_main, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        when (item.itemId) {
            R.id.action_change_server -> { showServerInput(); return true }
            R.id.action_clear_cache -> {
                AlertDialog.Builder(this)
                    .setMessage("Clear all cached data? This removes offline books and reading progress.")
                    .setPositiveButton("Clear") { _, _ ->
                        webView.clearCache(true)
                        webView.clearHistory()
                        deleteDatabase("webview.db")
                        deleteDatabase("webviewCache.db")
                        webView.reload()
                        Toast.makeText(this, "Cache cleared", Toast.LENGTH_SHORT).show()
                    }
                    .setNegativeButton("Cancel", null).show()
                return true
            }
            R.id.action_about -> {
                AlertDialog.Builder(this)
                    .setTitle("NovelHub")
                    .setMessage("Version 1.0\n\nWebView wrapper for NovelHub PWA.\nConnect to a LAN server to sync your library.")
                    .setPositiveButton("OK", null).show()
                return true
            }
        }
        return super.onOptionsItemSelected(item)
    }

    private fun configureWebView() {
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            setSupportZoom(false)
            useWideViewPort = true
            loadWithOverviewMode = true
        }
        webView.webViewClient = object : WebViewClient() {
            override fun onReceivedError(v: WebView?, r: WebResourceRequest?, e: WebResourceError?) {
                showErrorPage()
            }
        }
        webView.webChromeClient = WebChromeClient()
    }

    private fun loadServer() {
        val prefs = getSharedPreferences("novelhub", MODE_PRIVATE)
        serverUrl = prefs.getString("server_url", "") ?: ""
        if (serverUrl.isEmpty()) { showServerInput(); return }
        webView.loadUrl(serverUrl)
    }

    private fun showServerInput() {
        setContentView(R.layout.activity_server)
        val prefs = getSharedPreferences("novelhub", MODE_PRIVATE)
        val input = findViewById<android.widget.EditText>(R.id.serverInput)
        input.setText(prefs.getString("server_url", "") ?: "")
        findViewById<android.widget.Button>(R.id.btnConnect).setOnClickListener { connectFromInput() }
        findViewById<android.widget.TextView>(R.id.errorText).visibility = android.view.View.GONE
        findViewById<android.widget.Button>(R.id.btnRetry).visibility = android.view.View.GONE
    }

    private fun showErrorPage() {
        setContentView(R.layout.activity_server)
        val error = findViewById<android.widget.TextView>(R.id.errorText)
        error.visibility = android.view.View.VISIBLE
        error.text = "Cannot connect to server.\nCheck that the PC is on the same Wi-Fi and the server is running."
        findViewById<android.widget.Button>(R.id.btnRetry).visibility = android.view.View.VISIBLE
        findViewById<android.widget.Button>(R.id.btnRetry).setOnClickListener {
            setContentView(R.layout.activity_main)
            webView = findViewById(R.id.webView)
            configureWebView()
            loadServer()
        }
        findViewById<android.widget.Button>(R.id.btnConnect).setOnClickListener { connectFromInput() }
    }

    private fun connectFromInput() {
        val input = findViewById<android.widget.EditText>(R.id.serverInput)
        val url = input.text.toString().trim()
        if (url.isEmpty()) return
        getSharedPreferences("novelhub", MODE_PRIVATE).edit().putString("server_url", url).apply()
        serverUrl = url
        setContentView(R.layout.activity_main)
        webView = findViewById(R.id.webView)
        configureWebView()
        webView.loadUrl(url)
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            if (::webView.isInitialized && webView.canGoBack()) {
                webView.goBack(); return true
            }
            AlertDialog.Builder(this).setMessage("Exit NovelHub?")
                .setPositiveButton("Exit") { _, _ -> finish() }
                .setNegativeButton("Cancel", null).show()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }
}
