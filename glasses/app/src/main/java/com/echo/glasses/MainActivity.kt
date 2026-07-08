package com.echo.glasses

import android.content.IntentFilter
import android.os.Bundle
import android.util.Log
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.echo.glasses.receiver.KeyEventListener
import com.echo.glasses.receiver.KeyReceiver
import com.echo.glasses.receiver.KeyType
import com.rokid.cxr.CXRServiceBridge
import com.rokid.cxr.Caps

/**
 * 眼镜端 Echo CustomApp 入口（CXR-S 轻量应用）。
 *
 * 职责仅两项，与眼镜原有翻译/提词器等应用并存、不覆盖：
 * 1) subscribe("rk_custom_client") 接收手机端状态并在镜片显示（待机/记忆中/…）。
 * 2) 捕获物理按键（镜腿键/触控板/返回键）经 sendMessage("rk_custom_key") 上报手机端。
 *
 * 采集（音频/拍照）由眼镜固件经 CXR-L 直达手机，本 App 不采集媒体。
 * 由手机端 CXR-L appStart 拉起；同时保留 LAUNCHER 入口以便预装后出现在应用列表。
 */
class MainActivity : AppCompatActivity() {

    private companion object {
        const val TAG = "EchoGlass"
        /** 眼镜 → 手机上报通道，须与手机端 ICustomCmdCbk 过滤键一致。 */
        const val CMD_KEY = "rk_custom_key"
        /** 手机 → 眼镜订阅通道，须与手机端 sendCustomCmd 第一参数一致。 */
        const val CLIENT_KEY = "rk_custom_client"
    }

    private val bridge = CXRServiceBridge()
    private lateinit var statusText: TextView

    private val keyReceiver = KeyReceiver(KeyEventListener { keyType -> reportKey(keyType) })

    private val statusListener = object : CXRServiceBridge.StatusListener {
        override fun onConnected(p0: String?, p1: String?, p2: Int) {
            Log.d(TAG, "onConnected"); runOnUiThread { showStatus("已连接手机") }
        }
        override fun onDisconnected() {
            Log.d(TAG, "onDisconnected"); runOnUiThread { showStatus("手机已断开") }
        }
        override fun onConnecting(p0: String?, p1: String?, p2: Int) {}
        override fun onARTCStatus(p0: Float, p1: Boolean) {}
        override fun onRokidAccountChanged(p0: String?) {}
        override fun onAudioNoise(p0: Float) {}
    }

    private val msgCallback = object : CXRServiceBridge.MsgCallback {
        override fun onReceive(name: String?, args: Caps?, bytes: ByteArray?) {
            val text = args?.let { readLastString(it) }.orEmpty()
            Log.d(TAG, "onReceive name=$name text=$text")
            if (text.isNotBlank()) runOnUiThread { showStatus(text) }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        statusText = findViewById(R.id.statusText)
        showStatus(getString(R.string.status_idle))

        findViewById<Button>(R.id.btnToggle).setOnClickListener {
            // 触屏兜底：等价一次单击，交由手机端按录制状态处理。
            reportKey(KeyType.CLICK)
        }

        bridge.setStatusListener(statusListener)
        bridge.subscribe(CLIENT_KEY, msgCallback)

        registerReceiver(keyReceiver, IntentFilter().apply {
            KeyType.entries.forEach { addAction(it.action) }
        })
    }

    override fun onDestroy() {
        runCatching { unregisterReceiver(keyReceiver) }
        super.onDestroy()
    }

    /** 物理按键上报：Caps 首值标签 "action"，次值为动作名（手机端据此映射语义）。 */
    private fun reportKey(keyType: KeyType) {
        Log.d(TAG, "reportKey ${keyType.name}")
        bridge.sendMessage(CMD_KEY, Caps().apply {
            write("action")
            write(keyType.name)
        })
        showStatus("上报按键：${keyType.name}")
    }

    private fun showStatus(text: String) {
        statusText.text = text
    }

    private fun readLastString(caps: Caps): String {
        var last = ""
        for (i in 0 until caps.size()) {
            val v = caps.at(i)
            if (v.type() == Caps.Value.TYPE_STRING) last = v.string
        }
        return last
    }
}
