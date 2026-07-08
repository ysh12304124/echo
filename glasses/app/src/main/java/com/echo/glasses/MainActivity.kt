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
 * 职责：
 * 1) subscribe("rk_custom_client") 接收手机端状态并显示。
 * 2) 捕获触控板手势（TWO_FINGER_*）经 sendMessage("rk_custom_key") 上报手机；
 *    镜腿物理按键（CLICK/DOUBLE_CLICK）留给系统导航，不做录制控制。
 *
 * 采集（音频/拍照）由眼镜固件经 CXR-L 直达手机，本 App 不采集媒体。
 */
class MainActivity : AppCompatActivity() {

    private companion object {
        const val TAG = "EchoGlass"
        const val CMD_KEY = "rk_custom_key"
        const val CLIENT_KEY = "rk_custom_client"
    }

    private val bridge = CXRServiceBridge()
    private lateinit var statusText: TextView
    private var phoneStatus = ""

    private val keyReceiver = KeyReceiver(KeyEventListener { keyType -> reportKey(keyType) })

    private val statusListener = object : CXRServiceBridge.StatusListener {
        override fun onConnected(p0: String?, p1: String?, p2: Int) {
            Log.d(TAG, "onConnected"); runOnUiThread { showStatus("已连接") }
        }
        override fun onDisconnected() {
            Log.d(TAG, "onDisconnected"); runOnUiThread { showStatus("已断开") }
        }
        override fun onConnecting(p0: String?, p1: String?, p2: Int) {}
        override fun onARTCStatus(p0: Float, p1: Boolean) {}
        override fun onRokidAccountChanged(p0: String?) {}
        override fun onAudioNoise(p0: Float) {}
    }

    private val msgCallback = object : CXRServiceBridge.MsgCallback {
        override fun onReceive(name: String?, args: Caps?, bytes: ByteArray?) {
            val text = args?.let { readLastString(it) }.orEmpty()
            Log.d(TAG, "onReceive text=$text")
            if (text.isNotBlank()) {
                phoneStatus = text
                runOnUiThread { showStatus(text) }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        statusText = findViewById(R.id.statusText)
        showStatus("待机")

        findViewById<Button>(R.id.btnToggle).setOnClickListener {
            reportKey(KeyType.TWO_FINGER_SINGLE_TAP)
        }

        bridge.setStatusListener(statusListener)
        bridge.subscribe(CLIENT_KEY, msgCallback)

        registerReceiver(keyReceiver, IntentFilter().apply {
            // 仅注册触控板手势，不注册镜腿按键（留给系统导航）
            addAction(KeyType.TWO_FINGER_SINGLE_TAP.action)
            addAction(KeyType.TWO_FINGER_DOUBLE_TAP.action)
            addAction(KeyType.TWO_FINGER_SWIPE_FORWARD.action)
            addAction(KeyType.TWO_FINGER_SWIPE_BACK.action)
        })
    }

    override fun onDestroy() {
        runCatching { unregisterReceiver(keyReceiver) }
        super.onDestroy()
    }

    /** 手势上报：Caps 首值标签 "action"，次值为动作名。 */
    private fun reportKey(keyType: KeyType) {
        Log.d(TAG, "reportKey ${keyType.name}")
        bridge.sendMessage(CMD_KEY, Caps().apply {
            write("action")
            write(keyType.name)
        })
        // 不覆盖 status —— 保持手机端下发的状态显示
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
