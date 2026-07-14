package com.echo.glasses

import android.content.IntentFilter
import android.graphics.Color
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import android.util.Log
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.echo.glasses.receiver.KeyEventListener
import com.echo.glasses.receiver.KeyReceiver
import com.echo.glasses.receiver.KeyType
import com.rokid.cxr.CXRServiceBridge
import com.rokid.cxr.Caps

class MainActivity : AppCompatActivity() {

    private companion object {
        const val TAG = "ECHO_GLASS"
        const val CMD_KEY = "rk_custom_key"
        const val CLIENT_KEY = "rk_custom_client"
    }

    private enum class Scene(val cmd: String, val label: String) {
        ONSITE("ONSITE", "Onsite"),
        MEETING("MEETING", "Meeting"),
        QUALITY_TIME("QUALITY_TIME", "Quality"),
        SPACE("SPACE", "Space"),
    }

    private val scenes = Scene.values()
    private var selected = Scene.ONSITE.ordinal
    private var recording = false

    private val bridge = CXRServiceBridge()
    private lateinit var statusText: TextView
    private lateinit var hintText: TextView
    private lateinit var cloudText: TextView
    private lateinit var guideText: TextView
    private lateinit var sceneViews: List<TextView>

    private val keyReceiver = KeyReceiver(KeyEventListener { keyType -> onKey(keyType) })

    // ---- IMU ----
    private lateinit var sensorManager: SensorManager
    private var accel: Sensor? = null
    private var gyro: Sensor? = null
    private var imuActive = false
    private var lastAx = 0f; private var lastAy = 0f; private var lastAz = 0f
    private var lastGx = 0f; private var lastGy = 0f; private var lastGz = 0f

    private val imuListener = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            when (event.sensor.type) {
                Sensor.TYPE_ACCELEROMETER -> {
                    lastAx = event.values[0]; lastAy = event.values[1]; lastAz = event.values[2]
                }
                Sensor.TYPE_GYROSCOPE -> {
                    lastGx = event.values[0]; lastGy = event.values[1]; lastGz = event.values[2]
                    sendImuSample()
                }
            }
        }
        override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) {}
    }

    private fun startImu() {
        if (imuActive) return
        accel = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        gyro = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
        if (accel == null || gyro == null) { Log.w(TAG, "IMU 不可用"); return }
        sensorManager.registerListener(imuListener, accel, SensorManager.SENSOR_DELAY_GAME)
        sensorManager.registerListener(imuListener, gyro, SensorManager.SENSOR_DELAY_GAME)
        imuActive = true
        Log.i(TAG, "IMU 已启动")
    }

    private fun stopImu() {
        if (!imuActive) return
        sensorManager.unregisterListener(imuListener)
        imuActive = false
        Log.i(TAG, "IMU 已停止")
    }

    private fun sendImuSample() {
        if (!recording || !imuActive) return
        val caps = Caps().apply {
            write("imu")
            write(lastAx.toString()); write(lastAy.toString()); write(lastAz.toString())
            write(lastGx.toString()); write(lastGy.toString()); write(lastGz.toString())
            write(System.currentTimeMillis().toString())
        }
        bridge.sendMessage(CMD_KEY, caps)
    }
    // ---- IMU END ----

    private val statusListener = object : CXRServiceBridge.StatusListener {
        override fun onConnected(p0: String?, p1: String?, p2: Int) {
            Log.i(TAG, "bridge onConnected"); runOnUiThread { cloudText.text = "手机已连接" }
        }
        override fun onDisconnected() {
            Log.i(TAG, "bridge onDisconnected"); runOnUiThread { cloudText.text = "手机已断开" }
        }
        override fun onConnecting(p0: String?, p1: String?, p2: Int) {}
        override fun onARTCStatus(p0: Float, p1: Boolean) {}
        override fun onRokidAccountChanged(p0: String?) {}
        override fun onAudioNoise(p0: Float) {}
    }

    // phone → glasses messages via rk_custom_client
    // ["status", text] = status text (e.g. "待机")
    // ["guide", text] = recording guidance
    // ["feedback", text] = quality warning
    // ["loop_done", angle] = loop complete
    private val msgCallback = object : CXRServiceBridge.MsgCallback {
        override fun onReceive(name: String?, args: Caps?, bytes: ByteArray?) {
            if (args == null || args.size() < 2) return
            val tag = args.at(0).let { if (it.type() == Caps.Value.TYPE_STRING) it.string else null } ?: return
            val text = args.at(1).let { if (it.type() == Caps.Value.TYPE_STRING) it.string else null } ?: return
            when (tag) {
                "status" -> runOnUiThread { cloudText.text = "云端: $text" }
                "guide" -> runOnUiThread { guideText.text = text; guideText.visibility = android.view.View.VISIBLE }
                "feedback" -> runOnUiThread {
                    guideText.text = "! $text"
                    guideText.visibility = android.view.View.VISIBLE
                    guideText.postDelayed({
                        if (guideText.text.startsWith("!")) guideText.visibility = android.view.View.GONE
                    }, 2000)
                }
                "loop_done" -> runOnUiThread {
                    guideText.text = "回环完成($text°), 可停止或继续"
                    guideText.visibility = android.view.View.VISIBLE
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        sensorManager = getSystemService(SENSOR_SERVICE) as SensorManager
        statusText = findViewById(R.id.statusText)
        hintText = findViewById(R.id.hintText)
        cloudText = findViewById(R.id.cloudText)
        guideText = findViewById(R.id.guideText)
        sceneViews = listOf(
            findViewById(R.id.sceneOnsite),
            findViewById(R.id.sceneMeeting),
            findViewById(R.id.sceneQuality),
            findViewById(R.id.sceneSpace),
        )
        sceneViews.forEachIndexed { i, tv -> tv.setOnClickListener { onSceneTap(i) } }

        bridge.setStatusListener(statusListener)
        val subRet = bridge.subscribe(CLIENT_KEY, msgCallback)
        Log.i(TAG, "bridge 初始化 subscribe($CLIENT_KEY)=$subRet")

        registerReceiver(keyReceiver, IntentFilter().apply {
            addAction(KeyType.CLICK.action)
            addAction(KeyType.TWO_FINGER_SWIPE_FORWARD.action)
            addAction(KeyType.TWO_FINGER_SWIPE_BACK.action)
        })

        render()
        Log.i(TAG, "Echo 眼镜端启动 scenes=${scenes.size}")
    }

    override fun onDestroy() {
        stopImu()
        runCatching { unregisterReceiver(keyReceiver) }
        super.onDestroy()
    }

    private fun onKey(keyType: KeyType) {
        when (keyType) {
            KeyType.CLICK -> if (recording) stopMemory() else startMemory()
            KeyType.TWO_FINGER_SWIPE_FORWARD -> cycleScene(1)
            KeyType.TWO_FINGER_SWIPE_BACK -> cycleScene(-1)
            else -> {}
        }
    }

    private fun onSceneTap(index: Int) {
        if (!recording) { selected = index; startMemory() }
        else if (index == selected) stopMemory()
    }

    private fun cycleScene(delta: Int) {
        if (recording) return
        selected = ((selected + delta) % scenes.size + scenes.size) % scenes.size
        render()
    }

    private fun startMemory() {
        recording = true
        startImu()
        guideText.visibility = android.view.View.GONE
        val scene = scenes[selected]
        val ret = bridge.sendMessage(CMD_KEY, Caps().apply {
            write("cmd"); write("START"); write(scene.cmd)
        })
        Log.i(TAG, "发送 START ${scene.cmd} -> sendMessage($CMD_KEY) 返回=$ret")
        render()
    }

    private fun stopMemory() {
        recording = false
        stopImu()
        guideText.text = ""
        guideText.visibility = android.view.View.GONE
        val ret = bridge.sendMessage(CMD_KEY, Caps().apply {
            write("cmd"); write("STOP")
        })
        Log.i(TAG, "发送 STOP -> sendMessage($CMD_KEY) 返回=$ret")
        render()
    }

    private fun render() {
        val sceneColors = mapOf(
            0 to "#10B981", // Onsite green
            1 to "#2563EB", // Meeting blue
            2 to "#7C3AED", // Quality purple
            3 to "#F59E0B", // Space orange
        )
        sceneViews.forEachIndexed { i, tv ->
            val active = i == selected
            when {
                recording && active -> {
                    tv.setTextColor(Color.WHITE)
                    tv.setBackgroundColor(Color.parseColor(sceneColors[i] ?: "#3D5AFE"))
                }
                recording && !active -> {
                    tv.setTextColor(Color.parseColor("#555555"))
                    tv.setBackgroundColor(Color.TRANSPARENT)
                }
                active -> {
                    tv.setTextColor(Color.WHITE)
                    tv.setBackgroundColor(Color.parseColor(sceneColors[i] ?: "#3D5AFE"))
                }
                else -> {
                    tv.setTextColor(Color.parseColor("#AAAAAA"))
                    tv.setBackgroundColor(Color.TRANSPARENT)
                }
            }
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
}
