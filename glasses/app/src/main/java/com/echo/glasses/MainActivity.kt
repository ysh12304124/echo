package com.echo.glasses

import android.content.IntentFilter
import android.graphics.Color
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.util.Log
import android.view.View
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.echo.glasses.receiver.KeyEventListener
import com.echo.glasses.receiver.KeyReceiver
import com.echo.glasses.receiver.KeyType
import com.rokid.cxr.CXRServiceBridge
import com.rokid.cxr.Caps
import java.util.UUID
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {

    private companion object {
        const val TAG = "ECHO_GLASS"
        const val CMD_KEY = "rk_custom_key"
        const val CLIENT_KEY = "rk_custom_client"
        const val CHUNK = 50 * 1024
        const val IMU_INTERVAL_MS = 1000L
        const val MAX_SEND_RETRY = 5
        const val SEND_RETRY_DELAY_MS = 150L
    }

    private enum class Scene(val cmd: String, val label: String) {
        ONSITE("ONSITE", "Onsite"), MEETING("MEETING", "Meeting"), QUALITY_TIME("QUALITY_TIME", "Quality"),
    }

    private val scenes = Scene.values()
    private var sel = Scene.ONSITE.ordinal
    private var rec = false
    private var sid = ""
    private var spaceOn = false
    private var conn = false; private var phoneReady = false
    private var videoChunkIndex = 0
    private lateinit var vr: VideoRecorder

    private val bridge = CXRServiceBridge()
    private lateinit var st: TextView; private lateinit var ht: TextView
    private lateinit var ct: TextView; private lateinit var gt: TextView
    private lateinit var spaceTag: TextView
    private lateinit var sv: List<TextView>
    private val kr = KeyReceiver(KeyEventListener { onKey(it) })
    private val upExec = Executors.newSingleThreadExecutor()

    // ---- IMU(空间记忆开启时 1Hz 采样发送) ----
    private lateinit var sm: SensorManager
    private var ac: Sensor? = null; private var gy: Sensor? = null
    private var ia = false
    private var lax=0f; private var lay=0f; private var laz=0f
    private var lgx=0f; private var lgy=0f; private var lgz=0f
    private val imuHandler = Handler(Looper.getMainLooper())
    private val imuTask = object : Runnable {
        override fun run() { sendImu(); if (spaceOn) imuHandler.postDelayed(this, IMU_INTERVAL_MS) }
    }

    private val il = object : SensorEventListener {
        override fun onSensorChanged(e: SensorEvent) {
            when (e.sensor.type) {
                Sensor.TYPE_ACCELEROMETER -> { lax=e.values[0]; lay=e.values[1]; laz=e.values[2] }
                Sensor.TYPE_GYROSCOPE -> { lgx=e.values[0]; lgy=e.values[1]; lgz=e.values[2] }
            }
        }
        override fun onAccuracyChanged(s: Sensor, a: Int) {}
    }

    private fun startImuSensors() { if (ia) return; ac=sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER); gy=sm.getDefaultSensor(Sensor.TYPE_GYROSCOPE); if(ac==null||gy==null){Log.w(TAG,"no IMU");return}; sm.registerListener(il,ac,SensorManager.SENSOR_DELAY_GAME); sm.registerListener(il,gy,SensorManager.SENSOR_DELAY_GAME); ia=true }
    private fun stopImuSensors() { if(!ia)return; sm.unregisterListener(il); ia=false }
    // sendImu 由主线程 Handler 定时触发，sendCmd 内部可能 sleep 重试，必须丢到 upExec 后台线程执行，避免阻塞主线程/UI。
    private fun sendImu() { if(!spaceOn||!ia||!conn)return; val caps = Caps().apply { write("imu"); write(lax.toString()); write(lay.toString()); write(laz.toString()); write(lgx.toString()); write(lgy.toString()); write(lgz.toString()); write(System.currentTimeMillis().toString()) }; upExec.execute { sendCmd(caps, "imu") } }

    private fun toggleSpace() {
        spaceOn = !spaceOn
        if (spaceOn) { startImuSensors(); imuHandler.postDelayed(imuTask, IMU_INTERVAL_MS) }
        else { imuHandler.removeCallbacks(imuTask); stopImuSensors() }
        Log.i(TAG, "space memory = $spaceOn")
        // 主动上报开关状态，供手机端实时展示"3D记忆已开启/关闭"，不依赖 IMU 数据流的到达间接推断。
        upExec.execute { sendCmd(Caps().apply { write("space_state"); write(if (spaceOn) "on" else "off") }, "space_state") }
        render()
    }

    private val sl = object : CXRServiceBridge.StatusListener {
        override fun onConnected(p0:String?,p1:String?,p2:Int) { conn=true; runOnUiThread{ct.text="手机已连接"} }
        override fun onDisconnected() { conn=false; phoneReady=false; runOnUiThread{ct.text="手机已断开"} }
        override fun onConnecting(p0:String?,p1:String?,p2:Int) {}
        override fun onARTCStatus(p0:Float,p1:Boolean) {}
        override fun onRokidAccountChanged(p0:String?) {}
        override fun onAudioNoise(p0:Float) {}
    }

    private val mc = object : CXRServiceBridge.MsgCallback {
        override fun onReceive(name:String?,args:Caps?,bytes:ByteArray?) {
            if(args==null||args.size()<2)return
            phoneReady = true
            val tag=args.at(0).let{if(it.type()== Caps.Value.TYPE_STRING)it.string else null}?:return
            val text=args.at(1).let{if(it.type()== Caps.Value.TYPE_STRING)it.string else null}?:return
            when(tag) {
                "status"->runOnUiThread{ct.text="云端: $text"}
                "memory_complete"->{ Log.i(TAG, "memory_complete sid=$text (暂不删除本地视频,便于测试对照)") }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState); setContentView(R.layout.activity_main)
        // 屏幕息屏会触发 CXR 会话 onSessionPause(SESSION_SCREEN_OFF)，导致录制过程中指令通道被打断，
        // 常驻常亮以降低该情况出现概率（用于排查"眼镜发了但手机没收到"问题）。
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        sm = getSystemService(SENSOR_SERVICE) as SensorManager
        vr = VideoRecorder(this).apply {
            onChunk = { bytes -> sendVideoChunk(bytes) }
            onHeaderPatch = { bytes -> sendVideoPatch(bytes) }
            onVideoEnd = { filename -> sendVideoEnd(filename) }
        }
        st=findViewById(R.id.statusText); ht=findViewById(R.id.hintText)
        ct=findViewById(R.id.cloudText); gt=findViewById(R.id.guideText)
        spaceTag=findViewById(R.id.spaceTag)
        sv=listOf(findViewById(R.id.sceneOnsite),findViewById(R.id.sceneMeeting),findViewById(R.id.sceneQuality))
        sv.forEachIndexed{i,tv->tv.setOnClickListener{onTap(i)}}
        bridge.setStatusListener(sl); bridge.subscribe(CLIENT_KEY, mc)
        registerReceiver(kr, IntentFilter().apply {
            addAction(KeyType.CLICK.action)
            addAction(KeyType.TWO_FINGER_SWIPE_FORWARD.action)
            addAction(KeyType.TWO_FINGER_SWIPE_BACK.action)
            addAction(KeyType.TWO_FINGER_LONG_PRESS.action)
        })
        render()
        Log.i(TAG, "Echo start")
    }

    override fun onDestroy() {
        imuHandler.removeCallbacks(imuTask); stopImuSensors()
        vr.destroy(); upExec.shutdown(); runCatching{unregisterReceiver(kr)}; super.onDestroy()
    }

    private fun sendVideoChunk(bytes: ByteArray) {
        upExec.execute {
            var offset = 0
            while (offset < bytes.size) {
                val end = minOf(offset + CHUNK, bytes.size)
                val b64 = Base64.encodeToString(bytes, offset, end - offset, Base64.NO_WRAP)
                val idx = videoChunkIndex++
                sendCmd(Caps().apply { write("video_chunk"); write(sid); write(idx.toString()); write(b64) }, "video_chunk#$idx")
                offset = end
            }
        }
    }

    /** 用录制结束后重读的最终文件头部覆盖之前边录边发时的旧头部(见 VideoRecorder.HEADER_PATCH_BYTES)。 */
    private fun sendVideoPatch(bytes: ByteArray) {
        upExec.execute {
            val b64 = Base64.encodeToString(bytes, Base64.NO_WRAP)
            sendCmd(Caps().apply { write("video_patch"); write(sid); write("0"); write(b64) }, "video_patch")
            Log.i(TAG, "video_patch sent: ${bytes.size} bytes")
        }
    }

    private fun sendVideoEnd(filename: String) {
        upExec.execute {
            sendCmd(Caps().apply { write("video_end"); write(sid); write(filename) }, "video_end")
            Log.i(TAG, "video_end sent: $filename chunks=$videoChunkIndex")
        }
    }

    private fun onKey(k: KeyType) {
        when (k) {
            KeyType.CLICK -> if (rec) stop() else start()
            KeyType.TWO_FINGER_SWIPE_FORWARD -> cycle(1)
            KeyType.TWO_FINGER_SWIPE_BACK -> cycle(-1)
            // 双击(DOUBLE_CLICK)被系统占用为退出当前程序,单指长按被系统AI助手占用,双指单击实测难触发,双指双击也不理想,改用双指长按切换空间记忆。
            KeyType.TWO_FINGER_LONG_PRESS -> toggleSpace()
            else -> {}
        }
    }
    /** 统一发送并记录 CXRServiceBridge.sendMessage 的返回码。实测 ret=-3 集中出现在系统AI/息屏
     * 抢占本应用前台(CXR会话SESSION_AI_START/SESSION_SCREEN_OFF)期间——此时底层指令通道未就绪，
     * 是"短暂性"失败，恢复前台后通常能恢复发送。因此这里做有限次数的阻塞重试再放弃，避免一次抢占
     * 就永久丢失若干视频分片。必须在后台线程(upExec)调用，不可在主线程调用(内部会 sleep)。 */
    private fun sendCmd(caps: Caps, label: String) {
        var ret = bridge.sendMessage(CMD_KEY, caps)
        var attempt = 0
        while (ret != 0 && attempt < MAX_SEND_RETRY) {
            attempt++
            Log.w(TAG, "$label sendMessage ret=$ret，${SEND_RETRY_DELAY_MS}ms 后重试(第${attempt}次)")
            try { Thread.sleep(SEND_RETRY_DELAY_MS) } catch (_: InterruptedException) {}
            ret = bridge.sendMessage(CMD_KEY, caps)
        }
        if (ret != 0) Log.e(TAG, "$label sendMessage 重试${attempt}次后仍失败 ret=$ret 本条丢弃")
        else if (attempt > 0) Log.i(TAG, "$label sendMessage 重试第${attempt}次后成功")
    }

    private fun onTap(i: Int) { if(!rec){sel=i;start()} else if(i==sel)stop() }
    private fun cycle(d: Int) { if(rec)return; sel=((sel+d)%scenes.size+scenes.size)%scenes.size; render() }

    private fun start() {
        rec=true; sid=UUID.randomUUID().toString(); videoChunkIndex = 0
        val sc=scenes[sel]; vr.start(sc.label); gt.visibility=View.GONE
        val caps = Caps().apply{write("cmd");write("START");write(sc.cmd);write(sid)}
        upExec.execute { sendCmd(caps, "START") }
        Log.i(TAG, "START ${sc.cmd} $sid"); render()
    }

    private fun stop() {
        rec=false; val sc=scenes[sel]; vr.stop()
        gt.text=""; gt.visibility=View.GONE
        val caps = Caps().apply{write("cmd");write("STOP");write(sid)}
        upExec.execute { sendCmd(caps, "STOP") }
        Log.i(TAG, "STOP ${sc.cmd} $sid"); render()
    }

    private fun render() {
        val cc = mapOf(0 to "#10B981", 1 to "#2563EB", 2 to "#7C3AED")
        sv.forEachIndexed{i,tv->val a=i==sel; tv.setTextColor(if(rec&&a||a)Color.WHITE else if(rec)Color.parseColor("#555555") else Color.parseColor("#AAAAAA")); tv.setBackgroundColor(if(rec&&a||a)Color.parseColor(cc[i]?:("#3D5AFE")) else Color.TRANSPARENT); tv.isEnabled=!rec||a}
        st.text=if(rec)"记忆中 · ${scenes[sel].label}" else "待机 · ${scenes[sel].label}"
        ht.text=if(rec)"单击结束记忆" else "滑动切换场景 · 单击启动记忆 · 双指长按切换空间记忆"
        spaceTag.text=if(spaceOn)"空间记忆启动，imu记录中" else "空间记忆"
        spaceTag.setTextColor(if(spaceOn)Color.parseColor("#F59E0B") else Color.parseColor("#555555"))
    }
}
