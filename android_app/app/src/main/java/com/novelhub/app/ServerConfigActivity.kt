package com.novelhub.app

import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.novelhub.app.data.ApiClient

class ServerConfigActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ApiClient.init(this)

        val layout = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(48, 80, 48, 48); gravity = android.view.Gravity.CENTER }
        layout.addView(TextView(this).apply { text = "NovelHub"; textSize = 28f; setPadding(0, 0, 0, 32) })
        layout.addView(TextView(this).apply { text = "Enter LAN server address"; textSize = 14f; setTextColor(0xFF888888.toInt()); setPadding(0, 0, 0, 16) })

        val input = EditText(this).apply { hint = "http://192.168.1.100:8765"; setSingleLine(); setText(ApiClient.getServerUrl()) }
        layout.addView(input)

        val btn = Button(this).apply { text = "Connect" }
        btn.setOnClickListener {
            val url = input.text.toString().trim()
            if (url.isNotEmpty()) { ApiClient.setServerUrl(url); finish() }
        }
        layout.addView(btn)
        setContentView(layout)
    }
}
