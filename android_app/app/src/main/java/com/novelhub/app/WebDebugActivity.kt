package com.novelhub.app

import android.annotation.SuppressLint
import android.os.Bundle
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import com.novelhub.app.data.ApiClient

class WebDebugActivity : AppCompatActivity() {
    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ApiClient.init(this)
        val wv = WebView(this)
        wv.settings.apply { javaScriptEnabled = true; domStorageEnabled = true }
        wv.webViewClient = WebViewClient()
        setContentView(wv)
        wv.loadUrl(ApiClient.getServerUrl())
    }
}
