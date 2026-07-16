package com.echo.glasses

import android.content.ComponentName
import android.content.Intent
import android.content.ServiceConnection
import android.os.*
import android.util.Log
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

class OtaProbeActivity : AppCompatActivity() {
    companion object { const val TAG = "OTA_PROBE" }
    private val sb = StringBuilder()
    private lateinit var output: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        output = TextView(this).apply { textSize = 8f }
        setContentView(output)
        probe()
    }

    private fun probe() {
        sb.appendLine("=== OTA Probe ===")
        val intent = Intent().apply {
            setClassName("com.rokid.glass.ota", "com.rokid.glass.ota.component.CheckService")
        }
        bindService(intent, object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
                if (binder == null) { sb.appendLine("NULL"); finishProbe(); return }
                sb.appendLine("Connected: ${binder.interfaceDescriptor}")
                try {
                    val data = Parcel.obtain()
                    val reply = Parcel.obtain()
                    data.writeInterfaceToken(binder.interfaceDescriptor ?: "")
                    val ok = binder.transact(1, data, reply, 0)
                    sb.appendLine("checkOtaState: ok=$ok")
                    reply.setDataPosition(0)
                    if (reply.dataAvail() > 0) { sb.appendLine("result: ${reply.readString()}") }
                    data.recycle(); reply.recycle()
                } catch (e: Exception) { sb.appendLine("ERR: ${e.message}") }
                finishProbe()
            }
            override fun onServiceDisconnected(name: ComponentName?) { finishProbe() }
            override fun onBindingDied(name: ComponentName?) { sb.appendLine("died"); finishProbe() }
            override fun onNullBinding(name: ComponentName?) { sb.appendLine("NULL BIND"); finishProbe() }
        }, BIND_AUTO_CREATE)
        Thread { Thread.sleep(8000); if (!sb.contains("Connect")) { sb.appendLine("TIMEOUT"); finishProbe() } }.start()
    }

    private fun finishProbe() {
        sb.appendLine("=== Done ===")
        Log.i(TAG, sb.toString())
        runOnUiThread { output.text = sb.toString() }
    }
}
