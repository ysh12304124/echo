package com.echo.glasses

import android.content.Context
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.media.MediaRecorder
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import android.view.Surface
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class VideoRecorder(private val context: Context) {
    companion object { private const val TAG = "EchoVideo" }
    private var cm: CameraManager? = null
    private var dev: CameraDevice? = null
    private var ses: CameraCaptureSession? = null
    private var mr: MediaRecorder? = null
    private var thr: HandlerThread? = null
    private var hnd: Handler? = null
    private var cur: String? = null
    private var rec = false
    var onVideoReady: ((String) -> Unit)? = null

    fun start(onOk: (() -> Unit)? = null) {
        if (rec) return
        thr = HandlerThread("cam").also { it.start() }
        hnd = Handler(thr!!.looper)
        cm = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        hnd!!.post {
            try { newMR(); openCam(); rec = true; onOk?.invoke() }
            catch (e: Exception) { Log.e(TAG, "start: " + e.message) }
        }
    }

    private fun newMR() {
        val d = File(context.getExternalFilesDir(null), "Video/echo"); d.mkdirs()
        val ts = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        val f = File(d, "echo_$ts.tmp"); cur = f.absolutePath
        mr = MediaRecorder(context).apply {
            setVideoSource(MediaRecorder.VideoSource.SURFACE)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            setVideoFrameRate(30); setVideoSize(1280, 720)
            setVideoEncodingBitRate(2000000); setVideoEncoder(MediaRecorder.VideoEncoder.H264)
            setOutputFile(f.absolutePath); prepare()
        }
    }

    private fun openCam() {
        cm!!.openCamera("0", object : CameraDevice.StateCallback() {
            override fun onOpened(d: CameraDevice) { dev = d; cap(d, mr!!.surface) }
            override fun onDisconnected(d: CameraDevice) {
                // 相机被系统断开,不关session,MediaRecorder继续录
                Log.w(TAG, "disconnected, recording continues")
            }
            override fun onError(d: CameraDevice, e: Int) {
                Log.e(TAG, "err $e")
                // 不影响MediaRecorder,继续录
            }
        }, hnd)
    }

    private fun cap(d: CameraDevice, s: Surface) {
        d.createCaptureSession(listOf(s), object : CameraCaptureSession.StateCallback() {
            override fun onConfigured(ss: CameraCaptureSession) {
                ses = ss
                val r = d.createCaptureRequest(CameraDevice.TEMPLATE_RECORD).apply { addTarget(s) }
                ss.setRepeatingRequest(r.build(), null, hnd)
                mr!!.start()
                Log.i(TAG, "rec: $cur")
            }
            override fun onConfigureFailed(ss: CameraCaptureSession) { Log.e(TAG, "cfg fail") }
        }, hnd)
    }

    fun stop() {
        if (!rec) return; rec = false
        hnd?.post {
            try { mr?.stop() } catch (_: Exception) {}
            try { mr?.reset() } catch (_: Exception) {}
            mr?.release(); mr = null
            try { ses?.close() } catch (_: Exception) {}
            dev?.close(); dev = null; ses = null
            val p = cur ?: "?"; val f = File(p)
            Log.i(TAG, "stop: $p " + (if (f.exists()) f.length()/1024 else 0) + "KB")
            val tmpFile = java.io.File(cur ?: p); val mp4File = java.io.File(tmpFile.absolutePath.replace(".tmp",".mp4")); tmpFile.renameTo(mp4File); onVideoReady?.invoke(mp4File.absolutePath)
        }
    }

    fun destroy() { stop(); thr?.quitSafely() }
}
