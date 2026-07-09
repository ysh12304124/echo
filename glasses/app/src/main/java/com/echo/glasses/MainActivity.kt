package com.echo.glasses

import android.content.IntentFilter
import android.graphics.Color
import android.os.Bundle
import android.util.Log
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.echo.glasses.receiver.KeyEventListener
import com.echo.glasses.receiver.KeyReceiver
import com.echo.glasses.receiver.KeyType
import com.rokid.cxr.CXRServiceBridge
import com.rokid.cxr.Caps

/**
 * 眼镜端 Echo CustomApp：记忆控制中心。
 *
 * 交互（记忆完全由眼镜端主导）：
 *  - 进入后看到 3 个场景 Onsite / Meeting / Quality Time，默认选中 Onsite；
 *  - 待机时：滑动（双指前/后滑）在三个场景间切换选中项；
 *  - 单击选中的场景 → 启动记忆，上报 START(scene)，另两个场景置灰（不可选）；
 *  - 再次单击该场景 → 结束记忆，上报 STOP，另两个场景恢复可选。
 *
 * 显示：选择界面整体逆时针旋转 90°，以适配眼镜镜片显示方向。
 * 采集（音频/拍照）由眼镜固件经 CXR-L 直接送手机，本应用不采集媒体。
 */
class MainActivity : AppCompatActivity() {

    private companion object {
        const val TAG = "ECHO_GLASS"
        const val CMD_KEY = "rk_custom_key"
        const val CLIENT_KEY = "rk_custom_client"
    }

    /** 记忆场景，cmd 需与手机端 TimeScene 名称一致。 */
    private enum class Scene(val cmd: String, val label: String) {
        ONSITE("ONSITE", "Onsite"),
        MEETING("MEETING", "Meeting"),
        QUALITY_TIME("QUALITY_TIME", "Quality Time"),
    }

    private val scenes = Scene.values()
    private var selected = Scene.ONSITE.ordinal
    private var recording = false

    private val bridge = CXRServiceBridge()
    private lateinit var statusText: TextView
    private lateinit var hintText: TextView
    private lateinit var cloudText: TextView
    private lateinit var sceneViews: List<TextView>

    private val keyReceiver = KeyReceiver(KeyEventListener { keyType -> onKey(keyType) })

    private val statusListener = object : CXRServiceBridge.StatusListener {
        override fun onConnected(p0: String?, p1: String?, p2: Int) {
            Log.i(TAG, "bridge onConnected p0=$p0 p1=$p1 p2=$p2"); runOnUiThread { cloudText.text = "手机已连接" }
        }
        override fun onDisconnected() {
            Log.i(TAG, "bridge onDisconnected"); runOnUiThread { cloudText.text = "手机已断开" }
        }
        override fun onConnecting(p0: String?, p1: String?, p2: Int) {}
        override fun onARTCStatus(p0: Float, p1: Boolean) {}
        override fun onRokidAccountChanged(p0: String?) {}
        override fun onAudioNoise(p0: Float) {}
    }

    // 手机端经 rk_custom_client 回传的处理进度（如"上传完成"），仅作提示展示。
    private val msgCallback = object : CXRServiceBridge.MsgCallback {
        override fun onReceive(name: String?, args: Caps?, bytes: ByteArray?) {
            val text = args?.let { readLastString(it) }.orEmpty()
            Log.d(TAG, "onReceive text=$text")
            if (text.isNotBlank()) runOnUiThread { cloudText.text = "云端: $text" }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        statusText = findViewById(R.id.statusText)
        hintText = findViewById(R.id.hintText)
        cloudText = findViewById(R.id.cloudText)
        sceneViews = listOf(
            findViewById(R.id.sceneOnsite),
            findViewById(R.id.sceneMeeting),
            findViewById(R.id.sceneQuality),
        )
        // 单击场景选项：启动/结束该场景的记忆。
        sceneViews.forEachIndexed { i, tv -> tv.setOnClickListener { onSceneTap(i) } }

        bridge.setStatusListener(statusListener)
        val subRet = bridge.subscribe(CLIENT_KEY, msgCallback)
        Log.i(
            TAG,
            "bridge 初始化 subscribe($CLIENT_KEY)=$subRet " +
                "错误码定义 EINVAL=${CXRServiceBridge.EINVAL} EDUP=${CXRServiceBridge.EDUP} " +
                "EFAULT=${CXRServiceBridge.EFAULT} EBUSY=${CXRServiceBridge.EBUSY}",
        )

        registerReceiver(keyReceiver, IntentFilter().apply {
            addAction(KeyType.CLICK.action)
            addAction(KeyType.TWO_FINGER_SWIPE_FORWARD.action)
            addAction(KeyType.TWO_FINGER_SWIPE_BACK.action)
        })

        rotateForLens()
        render()
        Log.i(TAG, "Echo 眼镜端启动，已订阅 $CLIENT_KEY 并注册按键；默认场景=${scenes[selected].cmd}")
    }

    /** 选择界面整体逆时针旋转 90°，并交换宽高使其铺满镜片显示区域。 */
    private fun rotateForLens() {
        val root = findViewById<View>(R.id.root)
        val dm = resources.displayMetrics
        val w = dm.widthPixels
        val h = dm.heightPixels
        root.rotation = -90f
        // 旋转 90° 后需交换宽高（旋转前宽=屏高、高=屏宽），并居中避免裁剪。
        root.layoutParams = FrameLayout.LayoutParams(h, w, Gravity.CENTER)
    }

    override fun onDestroy() {
        runCatching { unregisterReceiver(keyReceiver) }
        super.onDestroy()
    }

    private fun onKey(keyType: KeyType) {
        Log.i(TAG, "onKey ${keyType.name} recording=$recording")
        when (keyType) {
            // 单击选中场景：待机→启动；记忆中→结束。
            KeyType.CLICK -> if (recording) stopMemory() else startMemory()
            // 滑动切换选中场景（仅待机时）。
            KeyType.TWO_FINGER_SWIPE_FORWARD -> cycleScene(1)
            KeyType.TWO_FINGER_SWIPE_BACK -> cycleScene(-1)
            else -> {}
        }
    }

    /** 点选某场景选项：待机→启动该场景；记忆中且为当前场景→结束；否则忽略（置灰）。 */
    private fun onSceneTap(index: Int) {
        if (!recording) {
            selected = index
            startMemory()
        } else if (index == selected) {
            stopMemory()
        }
    }

    private fun cycleScene(delta: Int) {
        if (recording) return // 记忆中不允许切换场景
        selected = ((selected + delta) % scenes.size + scenes.size) % scenes.size
        Log.i(TAG, "切换场景 -> ${scenes[selected].cmd}")
        render()
    }

    private fun startMemory() {
        recording = true
        val scene = scenes[selected]
        val ret = bridge.sendMessage(CMD_KEY, Caps().apply {
            write("cmd"); write("START"); write(scene.cmd)
        })
        Log.i(TAG, "发送 START ${scene.cmd} -> sendMessage($CMD_KEY) 返回=$ret (0=成功,负值=失败)")
        render()
    }

    private fun stopMemory() {
        recording = false
        val ret = bridge.sendMessage(CMD_KEY, Caps().apply {
            write("cmd"); write("STOP")
        })
        Log.i(TAG, "发送 STOP -> sendMessage($CMD_KEY) 返回=$ret (0=成功,负值=失败)")
        render()
    }

    private fun render() {
        sceneViews.forEachIndexed { i, tv ->
            val active = i == selected
            when {
                // 记忆中：选中场景高亮，其它两个置灰且不可点。
                recording && active -> {
                    tv.setTextColor(Color.WHITE)
                    tv.setBackgroundColor(Color.parseColor("#3D5AFE"))
                }
                recording && !active -> {
                    tv.setTextColor(Color.parseColor("#555555"))
                    tv.setBackgroundColor(Color.TRANSPARENT)
                }
                // 待机：选中场景高亮，其它两个可选。
                active -> {
                    tv.setTextColor(Color.WHITE)
                    tv.setBackgroundColor(Color.parseColor("#3D5AFE"))
                }
                else -> {
                    tv.setTextColor(Color.parseColor("#AAAAAA"))
                    tv.setBackgroundColor(Color.TRANSPARENT)
                }
            }
            // 记忆中仅允许点当前场景（用于结束），其它置灰不可点。
            tv.isEnabled = !recording || active
        }
        if (recording) {
            statusText.text = "记忆中 · ${scenes[selected].label}"
            hintText.text = "单击结束记忆"
        } else {
            statusText.text = "待机 · ${scenes[selected].label}"
            hintText.text = "滑动切换场景 · 单击启动记忆"
        }
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
