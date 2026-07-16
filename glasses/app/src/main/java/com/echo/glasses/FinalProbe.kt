package com.echo.glasses

import android.content.ComponentName
import android.content.Intent
import android.content.ServiceConnection
import android.os.*
import android.util.Log
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

class FinalProbeActivity : AppCompatActivity() {
    companion object { const val TAG = "FINAL_PROBE" }
    private val sb = StringBuilder()
    private lateinit var output: TextView
    private val handler = Handler(Looper.getMainLooper())
    private var frameCount = 0
    private var msgCount = 0

    // Use the proper AIDL Stub
    inner class ClientStub : IAssistClientStub() {
        override fun onRegisterResult(result: Int) {
            sb.appendLine("onRegisterResult: $result")
            updateUI()
        }
        override fun onMessageReceive(msg: String) {
            msgCount++
            sb.appendLine("onMsg($msgCount): ${msg.take(100)}")
            if (msgCount % 5 == 0) updateUI()
        }
        override fun onDataReceive(data: ByteArray) {
            frameCount++
            sb.appendLine("onData($frameCount): ${data.size}B")
            if (frameCount % 3 == 0) updateUI()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        output = TextView(this).apply { textSize = 8f }
        setContentView(output)
        probe()
    }

    private fun probe() {
        sb.appendLine("=== Final Probe ===")
        val intent = Intent("com.rokid.os.sprite.assist.MasterAssistService").apply {
            setClassName("com.rokid.os.sprite.assistserver",
                "com.rokid.os.sprite.assist.MasterAssistService")
        }
        bindService(intent, object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
                if (binder == null) { sb.appendLine("NULL BINDER"); finishProbe(); return }
                sb.appendLine("Connected: ${binder.interfaceDescriptor}")

                val client = ClientStub()

                // registerClient(packageName, client)
                try {
                    val data = Parcel.obtain()
                    val reply = Parcel.obtain()
                    data.writeString(packageName)
                    data.writeStrongBinder(client)
                    val ok = binder.transact(2, data, reply, 0)
                    sb.appendLine("registerClient: $ok")
                    // Read reply
                    reply.setDataPosition(0)
                    if (reply.dataAvail() > 0) {
                        try { sb.appendLine("  reply: ${reply.readString()}") } catch (_: Exception) {}
                    }
                    data.recycle(); reply.recycle()
                } catch (e: Exception) {
                    sb.appendLine("registerClient ERROR: ${e.message}")
                }

                // Send startCameraPage command
                handler.postDelayed({
                    try {
                        val data = Parcel.obtain()
                        val reply = Parcel.obtain()
                        data.writeInterfaceToken(binder.interfaceDescriptor ?: "")
                        data.writeString("""{"cmd":"startCameraPage"}""")
                        val ok = binder.transact(1, data, reply, 0)
                        sb.appendLine("startCameraPage: $ok")
                        data.recycle(); reply.recycle()
                    } catch (e: Exception) {
                        sb.appendLine("cmd ERROR: ${e.message}")
                    }
                }, 2000)

                // Wait for callbacks
                handler.postDelayed({ finishProbe() }, 15000)
            }
            override fun onServiceDisconnected(name: ComponentName?) { finishProbe() }
            override fun onBindingDied(name: ComponentName?) { sb.appendLine("BINDER DIED"); finishProbe() }
            override fun onNullBinding(name: ComponentName?) { sb.appendLine("NULL BIND"); finishProbe() }
        }, BIND_AUTO_CREATE)

        Thread {
            Thread.sleep(20000)
            if (!sb.contains("reg")) { sb.appendLine("TIMEOUT"); finishProbe() }
        }.start()
    }

    private fun updateUI() {
        runOnUiThread { output.text = sb.toString() }
    }

    private fun finishProbe() {
        sb.appendLine("=== Done (msgs=$msgCount frames=$frameCount) ===")
        Log.i(TAG, sb.toString())
        updateUI()
    }
}
