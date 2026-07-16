package com.echo.glasses

import android.content.IntentFilter
import android.graphics.Color
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import android.util.Base64
import android.util.Log
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.echo.glasses.receiver.KeyEventListener
import com.echo.glasses.receiver.KeyReceiver
import com.echo.glasses.receiver.KeyType
import com.rokid.cxr.CXRServiceBridge
import com.rokid.cxr.Caps
import java.io.File
import java.util.UUID
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {

    private companion object {
        const val TAG = "ECHO_GLASS"
        const val CMD_KEY = "rk_custom_key"
        const val CLIENT_KEY = "rk_custom_client"
        const val CHUNK = 50 * 1024
    }

    private enum class Scene(val cmd: String, val label: String) {
        ONSITE("ONSITE", "Onsite"), MEETING("MEETING", "Meeting"),
        QUALITY_TIME("QUALITY_TIME", "Quality"), SPACE("SPACE", "Space"),
    }

    private val scenes = Scene.values()
    private var sel = Scene.ONSITE.ordinal
    private var rec = false
    private var sid = ""
    private var conn = false; private var phoneReady = false
    private lateinit var vr: VideoRecorder

    private val bridge = CXRServiceBridge()
    private lateinit var st: TextView; private lateinit var ht: TextView
    private lateinit var ct: TextView; private lateinit var gt: TextView
    private lateinit var sv: List<TextView>
    private val kr = KeyReceiver(KeyEventListener { onKey(it) })
    private val upExec = Executors.newSingleThreadExecutor()
    private val hb = object : Runnable { override fun run() { flushDiskQueue(); android.os.Handler(android.os.Looper.getMainLooper()).postDelayed(this, 2000) } }

    // ---- IMU ----
    private lateinit var sm: SensorManager
    private var ac: Sensor? = null; private var gy: Sensor? = null
    private var ia = false
    private var lax=0f; private var lay=0f; private var laz=0f
    private var lgx=0f; private var lgy=0f; private var lgz=0f

    private val il = object : SensorEventListener {
        override fun onSensorChanged(e: SensorEvent) {
            when (e.sensor.type) {
                Sensor.TYPE_ACCELEROMETER -> { lax=e.values[0]; lay=e.values[1]; laz=e.values[2] }
                Sensor.TYPE_GYROSCOPE -> { lgx=e.values[0]; lgy=e.values[1]; lgz=e.values[2]; sendImu() }
            }
        }
        override fun onAccuracyChanged(s: Sensor, a: Int) {}
    }

    private fun startImu() { if (ia) return; ac=sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER); gy=sm.getDefaultSensor(Sensor.TYPE_GYROSCOPE); if(ac==null||gy==null){Log.w(TAG,"no IMU");return}; sm.registerListener(il,ac,SensorManager.SENSOR_DELAY_GAME); sm.registerListener(il,gy,SensorManager.SENSOR_DELAY_GAME); ia=true }
    private fun stopImu() { if(!ia)return; sm.unregisterListener(il); ia=false }
    private fun sendImu() { if(!rec||!ia||!conn)return; bridge.sendMessage(CMD_KEY, Caps().apply { write("imu"); write(lax.toString()); write(lay.toString()); write(laz.toString()); write(lgx.toString()); write(lgy.toString()); write(lgz.toString()); write(System.currentTimeMillis().toString()) }) }

    private val sl = object : CXRServiceBridge.StatusListener {
        override fun onConnected(p0:String?,p1:String?,p2:Int) { conn=true; runOnUiThread{ct.text="手机已连接"}; flushDiskQueue() }
        override fun onDisconnected() { conn=false; phoneReady=false; runOnUiThread{ct.text="手机已断开"} }
        override fun onConnecting(p0:String?,p1:String?,p2:Int) {}
        override fun onARTCStatus(p0:Float,p1:Boolean) {}
        override fun onRokidAccountChanged(p0:String?) {}
        override fun onAudioNoise(p0:Float) {}
    }

    private val mc = object : CXRServiceBridge.MsgCallback {
        override fun onReceive(name:String?,args:Caps?,bytes:ByteArray?) {
            if(args==null||args.size()<2)return
            phoneReady = true  // phone confirmed can receive
            val tag=args.at(0).let{if(it.type()== Caps.Value.TYPE_STRING)it.string else null}?:return
            val text=args.at(1).let{if(it.type()== Caps.Value.TYPE_STRING)it.string else null}?:return
            when(tag) {
                "status"->runOnUiThread{ct.text="云端: $text"}
                "guide"->runOnUiThread{gt.text=text;gt.visibility=android.view.View.VISIBLE}
                "feedback"->runOnUiThread{gt.text="! $text";gt.visibility=android.view.View.VISIBLE;gt.postDelayed({if(gt.text.startsWith("!"))gt.visibility=android.view.View.GONE},2000)}
                "loop_done"->runOnUiThread{gt.text="回环完成($text°), 可停止或继续";gt.visibility=android.view.View.VISIBLE}
                "video_ack"->{ val fn=args.at(1).let{if(it.type()==Caps.Value.TYPE_STRING)it.string else null}; if(fn!=null){val f=java.io.File(getExternalFilesDir(null),"Video/echo/"+fn);if(f.exists()){f.delete();};Log.i(TAG,"ack del: "+fn)} }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState); setContentView(R.layout.activity_main)
        sm = getSystemService(SENSOR_SERVICE) as SensorManager
        vr = VideoRecorder(this).apply { onVideoReady = { onReady(it) } }
        st=findViewById(R.id.statusText); ht=findViewById(R.id.hintText)
        ct=findViewById(R.id.cloudText); gt=findViewById(R.id.guideText)
        sv=listOf(findViewById(R.id.sceneOnsite),findViewById(R.id.sceneMeeting),findViewById(R.id.sceneQuality),findViewById(R.id.sceneSpace))
        sv.forEachIndexed{i,tv->tv.setOnClickListener{onTap(i)}}
        bridge.setStatusListener(sl); bridge.subscribe(CLIENT_KEY, mc)
        registerReceiver(kr, IntentFilter().apply { addAction(KeyType.CLICK.action); addAction(KeyType.TWO_FINGER_SWIPE_FORWARD.action); addAction(KeyType.TWO_FINGER_SWIPE_BACK.action) })
        render()
        Log.i(TAG, "Echo start")
        flushDiskQueue()
        android.os.Handler(android.os.Looper.getMainLooper()).postDelayed(hb, 5000)
    }

    override fun onDestroy() { stopImu(); vr.destroy(); android.os.Handler(android.os.Looper.getMainLooper()).removeCallbacks(hb); upExec.shutdown(); runCatching{unregisterReceiver(kr)}; super.onDestroy() }

    private fun onReady(path: String) {
        Log.i(TAG, "ready: ${scenes[sel].cmd} $sid $path")
        val json = "{\"sid\":\"" + sid + "\",\"scene\":\"" + scenes[sel].cmd + "\"}"
        java.io.File(path.replace(".mp4", ".json")).writeText(json)
        flushDiskQueue()
    }

    /** disk = upload queue: scan Video/echo/, upload each mp4, delete after success */
    private var lastFlushFile: String? = null
    private fun flushDiskQueue() {
        upExec.execute {
            val dir = File(getExternalFilesDir(null), "Video/echo")
            if (!dir.exists()) return@execute
            val files = dir.listFiles()?.filter { it.name.endsWith(".mp4") && it.length() > 0 }
                ?.sortedBy { it.lastModified() } ?: return@execute
            if (files.isEmpty()) return@execute
            // Only send FIRST file to avoid flooding CXR channel
            val f = files.first()
            // Skip if same file was just sent
            if (lastFlushFile == f.name) return@execute
            lastFlushFile = f.name
            // Read metadata from .json sidecar
            var metaSid = sid; var metaScene = scenes[sel].cmd
            val jf = java.io.File(f.absolutePath.replace(".mp4", ".json"))
            if (jf.exists()) {
                try {
                    val jo = org.json.JSONObject(jf.readText())
                    metaSid = jo.optString("sid", sid)
                    metaScene = jo.optString("scene", scenes[sel].cmd)
                } catch (e: Exception) { Log.w(TAG, "json: " + e.message) }
            }
                try {
                    val d = f.readBytes()
                    val t = (d.size + CHUNK - 1) / CHUNK
                    Log.i(TAG, "up " + f.name + " " + d.size + "B " + t + " chunks sid=" + metaSid + " scene=" + metaScene)
                    for (i in 0 until t) {
                        val s = i * CHUNK; val e = minOf(s + CHUNK, d.size)
                        val b64 = Base64.encodeToString(d, s, e - s, Base64.NO_WRAP)
                        bridge.sendMessage(CMD_KEY, Caps().apply {
                            write("video_chunk"); write(f.name); write(i.toString()); write(t.toString())
                            write(b64); write(metaSid); write(metaScene); write(System.currentTimeMillis().toString())
                        })
                    }
                    bridge.sendMessage(CMD_KEY, Caps().apply {
                        write("video_end"); write(f.name); write(metaSid); write(metaScene)
                    })
                Log.i(TAG, "up done: " + f.name)
                lastFlushFile = null
            } catch (e: Exception) { Log.e(TAG, "up err: " + f.name + " " + e.message, e); lastFlushFile = null }
        }
    }

    private fun onKey(k: KeyType) { when(k) { KeyType.CLICK->if(rec)stop() else start(); KeyType.TWO_FINGER_SWIPE_FORWARD->cycle(1); KeyType.TWO_FINGER_SWIPE_BACK->cycle(-1); else->{} } }
    private fun onTap(i: Int) { if(!rec){sel=i;start()} else if(i==sel)stop() }
    private fun cycle(d: Int) { if(rec)return; sel=((sel+d)%scenes.size+scenes.size)%scenes.size; render() }

    private fun start() {
        rec=true; sid=UUID.randomUUID().toString()
        val sc=scenes[sel]; vr.start(); startImu(); gt.visibility=android.view.View.GONE
        bridge.sendMessage(CMD_KEY, Caps().apply{write("cmd");write("START");write(sc.cmd);write(sid)})
        Log.i(TAG, "START ${sc.cmd} $sid"); render()
    }

    private fun stop() {
        rec=false; stopImu(); val sc=scenes[sel]; vr.stop()
        gt.text=""; gt.visibility=android.view.View.GONE
        bridge.sendMessage(CMD_KEY, Caps().apply{write("cmd");write("STOP");write(sid)})
        Log.i(TAG, "STOP ${sc.cmd} $sid"); render()
    }

    private fun render() {
        val cc = mapOf(0 to "#10B981", 1 to "#2563EB", 2 to "#7C3AED", 3 to "#F59E0B")
        sv.forEachIndexed{i,tv->val a=i==sel; tv.setTextColor(if(rec&&a||a)Color.WHITE else if(rec)Color.parseColor("#555555") else Color.parseColor("#AAAAAA")); tv.setBackgroundColor(if(rec&&a||a)Color.parseColor(cc[i]?:("#3D5AFE")) else Color.TRANSPARENT); tv.isEnabled=!rec||a }
        st.text=if(rec)"记忆中 · ${scenes[sel].label}" else "待机 · ${scenes[sel].label}"
        ht.text=if(rec)"单击结束记忆" else "滑动切换场景 · 单击启动记忆"
    }
}
