"""One-time script to generate Android skeleton files."""
import os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "android_app")


def write_file(rel_path, content):
    full = os.path.join(BASE, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content.lstrip("\n"))


# AndroidManifest.xml
write_file("app/src/main/AndroidManifest.xml", """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <application
        android:allowBackup="true"
        android:label="@string/app_name"
        android:icon="@drawable/ic_launcher"
        android:usesCleartextTraffic="true"
        android:theme="@style/Theme.NovelHub">
        <activity
            android:name=".MainActivity"
            android:configChanges="orientation|screenSize"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
""")

# build.gradle
write_file("app/build.gradle", """plugins {
    id 'com.android.application'
    id 'org.jetbrains.kotlin.android'
}
android {
    namespace 'com.novelhub.app'
    compileSdk 34
    defaultConfig {
        applicationId 'com.novelhub.app'
        minSdk 24
        targetSdk 34
        versionCode 1
        versionName '1.0'
    }
    buildTypes { release { minifyEnabled false } }
    compileOptions {
        sourceCompatibility JavaVersion.VERSION_17
        targetCompatibility JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = '17' }
}
dependencies {
    implementation 'androidx.core:core-ktx:1.12.0'
    implementation 'androidx.appcompat:appcompat:1.6.1'
    implementation 'com.google.android.material:material:1.11.0'
}
""")

# MainActivity.kt
write_file("app/src/main/java/com/novelhub/app/MainActivity.kt", """package com.novelhub.app

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
""")

# Layouts
write_file("app/src/main/res/layout/activity_main.xml", """<?xml version="1.0" encoding="utf-8"?>
<WebView xmlns:android="http://schemas.android.com/apk/res/android"
    android:id="@+id/webView"
    android:layout_width="match_parent"
    android:layout_height="match_parent" />
""")

write_file("app/src/main/res/layout/activity_server.xml", """<?xml version="1.0" encoding="utf-8"?>
<LinearLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    android:orientation="vertical"
    android:gravity="center"
    android:padding="32dp">
    <TextView android:text="NovelHub" android:textSize="28sp" android:textStyle="bold"
        android:layout_marginBottom="16dp" android:layout_width="wrap_content" android:layout_height="wrap_content" />
    <TextView android:text="Enter LAN server address" android:textSize="14sp" android:textColor="#888"
        android:layout_marginBottom="16dp" android:layout_width="wrap_content" android:layout_height="wrap_content" />
    <EditText android:id="@+id/serverInput" android:hint="http://192.168.1.100:8765"
        android:inputType="textUri" android:layout_marginBottom="16dp"
        android:layout_width="match_parent" android:layout_height="wrap_content" />
    <Button android:id="@+id/btnConnect" android:text="Connect"
        android:layout_width="match_parent" android:layout_height="wrap_content" />
    <Button android:id="@+id/btnRetry" android:text="Retry" android:visibility="gone"
        android:layout_width="match_parent" android:layout_height="wrap_content" />
</LinearLayout>
""")

# Resources
write_file("app/src/main/res/values/strings.xml", """<?xml version="1.0" encoding="utf-8"?>
<resources><string name="app_name">NovelHub</string></resources>
""")

write_file("app/src/main/res/values/styles.xml", """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="Theme.NovelHub" parent="Theme.AppCompat.Light.NoActionBar">
        <item name="colorPrimary">#4a90d9</item>
        <item name="colorPrimaryDark">#3a7bc8</item>
        <item name="colorAccent">#c0392b</item>
    </style>
</resources>
""")

write_file("app/src/main/res/drawable/ic_launcher.xml", """<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp" android:viewportWidth="108" android:viewportHeight="108">
    <path android:fillColor="#4a90d9" android:pathData="M54,54m-40,0a40,40 0,1 1,80 0a40,40 0,1 1,-80 0" />
    <path android:fillColor="#FFF" android:pathData="M38,38L54,50L70,38L70,70L38,70Z" />
</vector>
""")

print("Android skeleton files created successfully")
