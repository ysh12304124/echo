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

    fun start(): Boolean {
        if (audioRecord != null) return false
        val minBuffer = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        if (minBuffer <= 0) return false

        val recorder = try {
            AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                maxOf(minBuffer, 32_000),
            )
        } catch (error: Exception) {
            EchoLog.w("语音查询录音器创建失败: ${error.message}")
            return false
        }
        if (recorder.state != AudioRecord.STATE_INITIALIZED) {
            recorder.release()
            return false
        }

        try {
            recorder.startRecording()
        } catch (error: Exception) {
            EchoLog.w("语音查询录音启动失败: ${error.message}")
            recorder.release()
            return false
        }

        synchronized(lock) { buffer.reset() }
        audioRecord = recorder
        readJob = scope.launch {
            val chunk = ByteArray(maxOf(minBuffer, 4096))
            while (isActive) {
                val count = try {
                    recorder.read(chunk, 0, chunk.size)
                } catch (_: Exception) {
                    break
                }
                if (count <= 0) break
                synchronized(lock) {
                    val remaining = MAX_BYTES - buffer.size()
                    if (remaining > 0) buffer.write(chunk, 0, minOf(count, remaining))
                }
            }
        }
        return true
    }

    suspend fun stop(): ByteArray = withContext(Dispatchers.IO) {
        val recorder = audioRecord ?: return@withContext ByteArray(0)
        audioRecord = null
        try {
            recorder.stop()
        } catch (_: Exception) {
        }
        readJob?.cancelAndJoin()
        readJob = null
        recorder.release()
        synchronized(lock) {
            buffer.toByteArray().also { buffer.reset() }
        }
    }

    fun cancel() {
        val recorder = audioRecord
        audioRecord = null
        try {
            recorder?.stop()
        } catch (_: Exception) {
        }
        recorder?.release()
        readJob?.cancel()
        readJob = null
        synchronized(lock) { buffer.reset() }
    }

    companion object {
        const val SAMPLE_RATE = 16000
        const val MAX_SECONDS = 60
        const val MIN_DURATION_MS = 500
        const val MAX_BYTES = SAMPLE_RATE * 2 * MAX_SECONDS
        const val MIN_BYTES = SAMPLE_RATE * 2 * MIN_DURATION_MS / 1000
    }
}
