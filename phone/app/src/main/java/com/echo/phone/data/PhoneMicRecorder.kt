package com.echo.phone.data

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import com.echo.phone.domain.MediaAudio
import com.echo.phone.util.EchoLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream

/**
 * 手机端麦克风音频采集，输出格式与眼镜音频回调一致（PCM 16kHz/mono/16bit），
 * 通过 [audioFlow] 暴露，每 1 秒一块，时间戳使用 [System.currentTimeMillis]。
 */
class PhoneMicRecorder {

    private val _audioFlow = MutableSharedFlow<MediaAudio>(extraBufferCapacity = 128)
    val audioFlow: SharedFlow<MediaAudio> = _audioFlow.asSharedFlow()

    private var audioRecord: AudioRecord? = null
    private var readJob: Job? = null
    private val buffer = ByteArrayOutputStream()
    private val scope = CoroutineScope(Dispatchers.IO)

    private companion object {
        const val SAMPLE_RATE = 16000
        const val CHUNK_BYTES = 32_000 // 1 秒 PCM
    }

    /** 返回 true 表示启动成功，false 表示设备不支持该音频配置。 */
    fun start(): Boolean {
        if (audioRecord != null) return true
        val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        if (minBuf <= 0) {
            EchoLog.w("PhoneMicRecorder 启动失败: getMinBufferSize= (设备不支持 16kHz/mono/PCM)")
            return false
        }
        val bufSize = maxOf(minBuf, CHUNK_BYTES / 2)
        val recorder = try {
            AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufSize,
            )
        } catch (e: Exception) {
            EchoLog.w("PhoneMicRecorder 启动失败 AudioRecord 构造异常: ${e.message}")
            return false
        }
        try {
            recorder.startRecording()
        } catch (e: Exception) {
            EchoLog.w("PhoneMicRecorder 启动失败 startRecording 异常: ${e.message}")
            recorder.release()
            return false
        }
        audioRecord = recorder
        buffer.reset()
        EchoLog.i("PhoneMicRecorder 已启动 sampleRate= bufSize=")

        val readBuf = ByteArray(minBuf)
        readJob = scope.launch {
            while (isActive) {
                val n = withContext(Dispatchers.IO) { recorder.read(readBuf, 0, readBuf.size) }
                if (n <= 0) continue
                buffer.write(readBuf, 0, n)
                if (buffer.size() >= CHUNK_BYTES) {
                    val chunk = buffer.toByteArray()
                    buffer.reset()
                    _audioFlow.tryEmit(MediaAudio(chunk, System.currentTimeMillis()))
                }
            }
        }
        return true
    }

    /** 停止采集，flush 尾部残余数据到 [audioFlow]，释放 AudioRecord。 */
    fun stop() {
        readJob?.cancel()
        readJob = null
        val recorder = audioRecord ?: return
        audioRecord = null
        try {
            recorder.stop()
            val tailBuf = ByteArray(recorder.bufferSizeInFrames * 2)
            while (true) {
                val n = recorder.read(tailBuf, 0, tailBuf.size)
                if (n <= 0) break
                buffer.write(tailBuf, 0, n)
            }
            recorder.release()
        } catch (e: Exception) {
            EchoLog.w("PhoneMicRecorder stop 异常: ${e.message}")
        }
        if (buffer.size() > 0) {
            val tail = buffer.toByteArray()
            buffer.reset()
            _audioFlow.tryEmit(MediaAudio(tail, System.currentTimeMillis()))
            EchoLog.i("PhoneMicRecorder 尾部 flush ${tail.size} 字节")
        }
        EchoLog.i("PhoneMicRecorder 已停止")
    }
}
