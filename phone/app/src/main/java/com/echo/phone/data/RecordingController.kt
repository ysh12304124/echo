package com.echo.phone.data

import com.echo.phone.data.glasses.GlassesConnection
import com.echo.phone.domain.*
import com.echo.phone.util.EchoLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.atomic.AtomicInteger

/**
 * 记忆录制编排：场景 START 后同时收集视频分片(不落地转发)、手机麦克风音频、IMU(空间记忆开启时)。
 * STOP 后等视频/音频/IMU 全部上传完成才 complete，成功后再通知眼镜端。
 */
class RecordingController(
    private val repo: EchoRepository,
    private val glasses: GlassesConnection,
    private val scope: CoroutineScope,
) {
    private var sessionId: String? = null
    private var glassSid: String? = null
    private var imuJob: Job? = null
    private var videoJob: Job? = null
    private var micJob: Job? = null
    private val mic = PhoneMicRecorder()

    private val imuBatchLock = Any()
    private val pendingImuBatch = mutableListOf<ImuSample>()

    @Volatile private var videoDone = false
    private val pendingUploads = AtomicInteger(0)

    val currentSessionId: String? get() = sessionId

    suspend fun startTime(scene: TimeScene, partition: DataPartition, title: String, glassSid: String?): String {
        val id = repo.startSession(MemoryType.TIME, scene, partition, title)
        EchoLog.i("创建会话 session=$id scene=$scene partition=$partition glassSid=$glassSid")
        sessionId = id
        this.glassSid = glassSid
        videoDone = false
        collectImu(id)
        collectVideo(id)
        startMic(id)
        glasses.startTimeRecording(scene, partition)
        return id
    }

    private fun collectImu(id: String) {
        imuJob = scope.launch {
            glasses.imuFlow.collect { imu ->
                val chunk = synchronized(imuBatchLock) {
                    pendingImuBatch += imu
                    if (pendingImuBatch.size >= 25) pendingImuBatch.toList().also { pendingImuBatch.clear() } else null
                }
                if (chunk != null) uploadTracked { uploadImuBatch(id, chunk) }
            }
        }
    }

    /**
     * 视频分片必须严格按 index 顺序串行 POST，后台按到达顺序 append 再在收到末片时 rename；
     * 因此这里在 collect 内部直接 await 每次上传（而非像音频/IMU 那样用 [uploadTracked] 并发甩出去），
     * 否则并发乱序会导致 video_end 抢在前面分片写完之前触发过早 rename，成片被截断。
     */
    private fun collectVideo(id: String) {
        videoJob = scope.launch {
            glasses.videoChunkFlow.collect { chunk ->
                when (chunk) {
                    is VideoChunk.Data -> {
                        if (glassSid != null && chunk.streamId != glassSid) return@collect
                        uploadVideoSequential { repo.uploadVideoChunk(id, chunk.index, false, null, chunk.bytes) }
                    }
                    is VideoChunk.Patch -> {
                        if (glassSid != null && chunk.streamId != glassSid) return@collect
                        uploadVideoSequential { repo.patchVideoHeader(id, chunk.offset, chunk.bytes) }
                    }
                    is VideoChunk.End -> {
                        if (glassSid != null && chunk.streamId != glassSid) return@collect
                        uploadVideoSequential { repo.uploadVideoChunk(id, -1, true, chunk.filename, ByteArray(0)) }
                        videoDone = true
                        EchoLog.i("视频分片接收完毕 session=$id filename=${chunk.filename}")
                    }
                }
            }
        }
    }

    private suspend fun uploadVideoSequential(block: suspend () -> Unit) {
        pendingUploads.incrementAndGet()
        try { block() } catch (e: Exception) { EchoLog.e("视频分片上传失败: ${e.message}", e) }
        finally { pendingUploads.decrementAndGet() }
    }

    private fun startMic(id: String) {
        micJob = scope.launch {
            mic.audioFlow.collect { audio -> uploadTracked { repo.uploadAudio(id, audio) } }
        }
        if (!mic.start()) EchoLog.w("手机麦克风启动失败，本次记忆将缺失音频 session=$id")
    }

    private fun uploadTracked(block: suspend () -> Unit) {
        pendingUploads.incrementAndGet()
        scope.launch {
            try { block() } catch (e: Exception) { EchoLog.e("上传失败: ${e.message}", e) }
            finally { pendingUploads.decrementAndGet() }
        }
    }

    private suspend fun uploadImuBatch(id: String, samples: List<ImuSample>) {
        repo.uploadImuBatch(id, samples)
        EchoLog.i("IMU batch uploaded session=$id count=${samples.size}")
    }

    suspend fun stopAndComplete(): MemorySummary {
        val id = sessionId ?: throw IllegalStateException("No active session")
        glasses.stopRecording()
        mic.stop()

        withTimeoutOrNull(UPLOAD_DRAIN_TIMEOUT_MS) {
            delay(300) // 留出时间让麦克风尾块/眼镜尾部视频分片进入上传队列
            while (!videoDone || pendingUploads.get() > 0) delay(100)
        } ?: EchoLog.w("等待视频/音频上传排空超时 session=$id videoDone=$videoDone pending=${pendingUploads.get()}")

        imuJob?.cancelAndJoin(); imuJob = null
        videoJob?.cancelAndJoin(); videoJob = null
        micJob?.cancelAndJoin(); micJob = null

        val tailImu = synchronized(imuBatchLock) {
            pendingImuBatch.toList().also { pendingImuBatch.clear() }
        }
        if (tailImu.isNotEmpty()) uploadImuBatch(id, tailImu)

        val summary = repo.completeSession(id)
        val sidForGlass = glassSid ?: id
        runCatching { glasses.sendMemoryComplete(sidForGlass) }
        sessionId = null; glassSid = null
        return summary
    }

    private companion object {
        const val UPLOAD_DRAIN_TIMEOUT_MS = 15_000L
    }
}
