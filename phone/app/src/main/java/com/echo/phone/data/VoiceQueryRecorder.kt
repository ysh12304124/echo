package com.echo.phone.data

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import com.echo.phone.util.EchoLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream

class VoiceQueryRecorder {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val buffer = ByteArrayOutputStream(MAX_BYTES)
    private val lock = Any()

    private var audioRecord: AudioRecord? = null
    private var readJob: Job? = null
    @Volatile private var closing = false

    fun start(): Boolean {
        if (closing || audioRecord != null) return false
        val minBuffer = try {
            AudioRecord.getMinBufferSize(
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
        } catch (error: Throwable) {
            EchoLog.w("语音查询录音缓冲区获取失败: ${error.message}")
            return false
        }
        if (minBuffer <= 0) return false

        val recorder = try {
            AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                maxOf(minBuffer, 32_000),
            )
        } catch (error: Throwable) {
            EchoLog.w("语音查询录音器创建失败: ${error.message}")
            return false
        }
        if (recorder.state != AudioRecord.STATE_INITIALIZED) {
            safeRelease(recorder)
            return false
        }

        try {
            recorder.startRecording()
        } catch (error: Throwable) {
            EchoLog.w("语音查询录音启动失败: ${error.message}")
            safeRelease(recorder)
            return false
        }

        synchronized(lock) { buffer.reset() }
        audioRecord = recorder
        readJob = scope.launch {
            try {
                val chunk = ByteArray(maxOf(minBuffer, 4096))
                while (isActive) {
                    val count = try {
                        recorder.read(chunk, 0, chunk.size)
                    } catch (error: Throwable) {
                        EchoLog.w("语音查询录音读取结束: ${error.message}")
                        break
                    }
                    if (count <= 0) break
                    synchronized(lock) {
                        val remaining = MAX_BYTES - buffer.size()
                        if (remaining > 0) buffer.write(chunk, 0, minOf(count, remaining))
                    }
                }
            } catch (error: Throwable) {
                EchoLog.e("语音查询录音读取异常: ${error.message}", error)
            }
        }
        return true
    }

    suspend fun stop(): ByteArray = withContext(Dispatchers.IO) {
        val recorder = audioRecord ?: return@withContext ByteArray(0)
        closing = true
        audioRecord = null
        try { recorder.stop() } catch (_: Throwable) { }
        try {
            readJob?.cancelAndJoin()
        } catch (error: Throwable) {
            EchoLog.w("语音查询录音读取任务停止异常: ${error.message}")
        } finally {
            readJob = null
            safeRelease(recorder)
            closing = false
        }
        synchronized(lock) { buffer.toByteArray().also { buffer.reset() } }
    }

    suspend fun cancelAndDiscard() = withContext(Dispatchers.IO) {
        val recorder = audioRecord ?: return@withContext
        closing = true
        audioRecord = null
        try { recorder.stop() } catch (_: Throwable) { }
        try {
            readJob?.cancelAndJoin()
        } catch (error: Throwable) {
            EchoLog.w("语音查询取消读取任务异常: ${error.message}")
        } finally {
            readJob = null
            safeRelease(recorder)
            synchronized(lock) { buffer.reset() }
            closing = false
        }
    }

    fun cancel() {
        val recorder = audioRecord ?: run {
            synchronized(lock) { buffer.reset() }
            return
        }
        closing = true
        audioRecord = null
        val job = readJob
        readJob = null
        scope.launch {
            try { recorder.stop() } catch (_: Throwable) { }
            try { job?.cancelAndJoin() } catch (error: Throwable) {
                EchoLog.w("语音查询后台取消读取任务异常: ${error.message}")
            } finally {
                safeRelease(recorder)
                synchronized(lock) { buffer.reset() }
                closing = false
            }
        }
    }

    private fun safeRelease(recorder: AudioRecord) {
        try { recorder.release() } catch (error: Throwable) {
            EchoLog.w("语音查询录音释放异常: ${error.message}")
        }
    }

    companion object {
        const val SAMPLE_RATE = 16_000
        const val MAX_SECONDS = 60
        const val MIN_DURATION_MS = 500
        const val MAX_BYTES = SAMPLE_RATE * 2 * MAX_SECONDS
        const val MIN_BYTES = SAMPLE_RATE * 2 * MIN_DURATION_MS / 1000
    }
}
