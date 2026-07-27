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
import java.io.RandomAccessFile
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 仅录制视频(无音频源),边录边把新写入的字节通过 [onChunk] 吐出,
 * 录制结束后重命名为 场景_开始时间_结束时间.mp4 并通过 [onVideoEnd] 通知文件名。
 */
class VideoRecorder(private val context: Context) {
    companion object {
        private const val TAG = "EchoVideo"
        private const val CHUNK_INTERVAL_MS = 800L
        // MediaRecorder 在 stop() 时会回改文件头部(如 mdat box 的 64bit size 占位值)，
        // 该区域在录制期间已被边录边发发出过旧值，需要收尾后重读最终文件的头部这么多字节再覆盖一次。
        private const val HEADER_PATCH_BYTES = 8 * 1024
        private val TS_FORMAT get() = SimpleDateFormat("yyyyMMddHHmmss", Locale.US)
    }

    private var cm: CameraManager? = null
    private var dev: CameraDevice? = null
    private var ses: CameraCaptureSession? = null
    private var mr: MediaRecorder? = null
    private var thr: HandlerThread? = null
    private var hnd: Handler? = null
    private var cur: String? = null
    private var rec = false
    private var sentOffset: Long = 0
    private var scene: String = ""
    private var startTs: String = ""

    /** 新写入的视频字节(边录边吐,含收尾时的最后一批,包含 moov)。 */
    var onChunk: ((ByteArray) -> Unit)? = null
    /** 录制结束后用最终文件头部覆盖之前边录边发时发出的旧头部(见 [HEADER_PATCH_BYTES])。 */
    var onHeaderPatch: ((ByteArray) -> Unit)? = null
    /** 录制彻底结束、文件已重命名后回调最终文件名。 */
    var onVideoEnd: ((String) -> Unit)? = null

    private val chunkTask = object : Runnable {
        override fun run() {
            readAndEmit()
            if (rec) hnd?.postDelayed(this, CHUNK_INTERVAL_MS)
        }
    }

    fun start(sceneLabel: String, onOk: (() -> Unit)? = null) {
        if (rec) return
        scene = sceneLabel
        startTs = TS_FORMAT.format(Date())
        sentOffset = 0
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
        val f = File(d, "echo_$startTs.tmp"); cur = f.absolutePath
        mr = MediaRecorder(context).apply {
            setVideoSource(MediaRecorder.VideoSource.SURFACE)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            setVideoFrameRate(30); setVideoSize(2048, 1536)
            setVideoEncodingBitRate(2000000); setVideoEncoder(MediaRecorder.VideoEncoder.H264)
            setOrientationHint(0)
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
                hnd?.postDelayed(chunkTask, CHUNK_INTERVAL_MS)
            }
            override fun onConfigureFailed(ss: CameraCaptureSession) { Log.e(TAG, "cfg fail") }
        }, hnd)
    }

    /** 读取自上次发送后新增的字节并通过 [onChunk] 吐出。 */
    private fun readAndEmit() {
        val p = cur ?: return
        val f = File(p)
        if (!f.exists()) return
        val len = f.length()
        if (len <= sentOffset) return
        try {
            RandomAccessFile(f, "r").use { raf ->
                raf.seek(sentOffset)
                val toRead = (len - sentOffset).toInt()
                val buf = ByteArray(toRead)
                raf.readFully(buf)
                sentOffset = len
                onChunk?.invoke(buf)
            }
        } catch (e: Exception) { Log.e(TAG, "chunk read: " + e.message) }
    }

    fun stop() {
        if (!rec) return; rec = false
        hnd?.removeCallbacks(chunkTask)
        hnd?.post {
            val stopped = runCatching { mr?.stop() }.isSuccess
            if (!stopped) {
                Log.e(TAG, "stop failed; refusing to publish an incomplete video")
                runCatching { mr?.reset() }
                mr?.release(); mr = null
                runCatching { ses?.close() }
                dev?.close(); dev = null; ses = null
                return@post
            }
            readAndEmit() // 收尾:mr.stop()后文件已落盘(含moov),把剩余字节发完
            try { mr?.reset() } catch (_: Exception) {}
            mr?.release(); mr = null
            try { ses?.close() } catch (_: Exception) {}
            dev?.close(); dev = null; ses = null
            val tmpFile = File(cur ?: return@post)
            val endTs = TS_FORMAT.format(Date())
            val finalName = "${scene}_${startTs}_${endTs}.mp4"
            val finalFile = File(tmpFile.parentFile, finalName)
            tmpFile.renameTo(finalFile)
            Log.i(TAG, "stop: ${finalFile.absolutePath} " + (if (finalFile.exists()) finalFile.length() / 1024 else 0) + "KB")
            sendHeaderPatch(finalFile)
            onVideoEnd?.invoke(finalName)
        }
    }

    /**
     * MediaRecorder 的 mdat box 64bit size 字段等头部信息只有 stop() 之后才是最终值，
     * 而这段字节在录制期间已经用占位值边录边发出去过；这里重读最终文件的头部再发一次覆盖旧值，
     * 必须在 [onVideoEnd] 之前调用，backend 才能在收到 video_end(触发 rename)前完成覆盖。
     */
    private fun sendHeaderPatch(finalFile: File) {
        try {
            RandomAccessFile(finalFile, "r").use { raf ->
                val len = minOf(HEADER_PATCH_BYTES.toLong(), raf.length()).toInt()
                val buf = ByteArray(len)
                raf.seek(0)
                raf.readFully(buf)
                onHeaderPatch?.invoke(buf)
            }
        } catch (e: Exception) { Log.e(TAG, "header patch read: " + e.message) }
    }

    fun destroy() { stop(); thr?.quitSafely() }
}
