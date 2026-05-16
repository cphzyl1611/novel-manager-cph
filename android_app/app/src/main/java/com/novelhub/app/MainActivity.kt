package com.novelhub.app

import android.annotation.SuppressLint
import android.os.Bundle
import android.view.KeyEvent
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
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
            override fun onReceivedError(
                view: WebView?, request: WebResourceRequest?, error: WebResourceError?
            ) { showErrorPage() }
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
        val input = findViewById<android.widget.EditText>(R.id.serverInput)
        val prefs = getSharedPreferences("novelhub", MODE_PRIVATE)
        input.setText(prefs.getString("server_url", "") ?: "")
        findViewById<android.widget.Button>(R.id.btnConnect).setOnClickListener { connectFromInput() }
    }

    private fun showErrorPage() {
        setContentView(R.layout.activity_server)
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
