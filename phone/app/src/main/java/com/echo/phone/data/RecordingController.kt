package com.echo.phone.data

import com.echo.phone.data.glasses.GlassesConnection
import com.echo.phone.domain.*
import com.echo.phone.util.EchoLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File
import java.io.RandomAccessFile
import java.util.concurrent.atomic.AtomicInteger

/** 首页"上传状态"栏展示用：本次记忆各类数据的上传进度，全部结束一段时间后 [visible] 转 false 自动隐藏。 */
data class UploadStatus(
    val visible: Boolean = false,
    val spaceEnabled: Boolean = false,
    val videoDone: Boolean = false,
    val audioDone: Boolean = false,
    val imuDone: Boolean = false,
)

/** 旁路 SPACE 会话状态：TIME 录制中用户开启 SPACE 时,把后续视频分片落本地,结束时上传。 */
private data class InlineSpaceSession(
    val sessionId: String,
    val sceneType: SpaceSceneType,
    val cacheFile: File,
    val raf: RandomAccessFile,
    var closed: Boolean = false,
    var finalizing: Boolean = false,
    var finalized: Boolean = false,
)

/** 用眼镜端提供的绝对 offset 覆盖 MP4 的最终头部，保留 offset 之前的 ftyp/free。 */
internal fun applyVideoPatch(raf: RandomAccessFile, offset: Long, bytes: ByteArray) {
    require(offset >= 0) { "video patch offset must be non-negative" }
    raf.seek(offset)
    raf.write(bytes)
}

/** 将视频尾部分片追加到缓存文件末尾。调用方负责保证文件处于可写状态。 */
internal fun appendVideoChunk(raf: RandomAccessFile, bytes: ByteArray) {
    raf.seek(raf.length())
    raf.write(bytes)
}

/** SPACE 本地文件只有拿到最终头部且收到视频结束标志后才允许 finalize。 */
internal fun canFinalizeSpace(headerPatchReceived: Boolean, videoDone: Boolean): Boolean =
    headerPatchReceived && videoDone

/**
 * 记忆录制编排：场景 START 后同时收集视频分片(不落地转发)、手机麦克风音频、IMU(空间记忆开启时)。
 * STOP 后等视频/音频/IMU 全部上传完成才 complete，成功后再通知眼镜端。
 */
class RecordingController(
    private val repo: EchoRepository,
    private val glasses: GlassesConnection,
    private val scope: CoroutineScope,
    private val cacheDir: File,
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
    @Volatile private var micStopped = false
    @Volatile private var imuStopped = false
    @Volatile private var spaceUsedInSession = false
    @Volatile private var uploadBarVisible = false
    private val pendingUploads = AtomicInteger(0)
    private val pendingVideoUploads = AtomicInteger(0)
    private val pendingAudioUploads = AtomicInteger(0)
    private val pendingImuUploads = AtomicInteger(0)

    /** idx=0 分片缓存(含 ftyp+moov MP4 头),用于旁路 SPACE 会话本地文件的初始化。 */
    @Volatile private var mp4HeaderCache: ByteArray? = null

    /** 标记是否已收到眼镜端的 header patch(真正的 moov box)。 */
    @Volatile private var headerPatchReceived: Boolean = false

    /** 旁路 SPACE 会话(TIME 录制中用户开启 SPACE):后续分片同步落本地,结束时上传。 */
    @Volatile private var inlineSpace: InlineSpaceSession? = null

    /** SPACE UI 已结束但整体 TIME 视频尚未 finalize 时保留的会话。 */
    @Volatile private var pendingSpace: InlineSpaceSession? = null

    /** 最近收到视频事件的时间，用于覆盖眼镜端 video_end 后仍到达的尾部 chunk。 */
    @Volatile private var lastVideoChunkAtNanos: Long = 0L

    private val _uploadStatus = MutableStateFlow(UploadStatus())
    val uploadStatus: StateFlow<UploadStatus> = _uploadStatus.asStateFlow()

    /** 当前是否有活跃的旁路 SPACE 录制(供 UI 显示"3D 记忆中"状态)。 */
    val isInlineSpaceActive: Boolean get() = inlineSpace != null

    val currentSessionId: String? get() = sessionId

    private fun publishUploadStatus() {
        _uploadStatus.value = UploadStatus(
            visible = uploadBarVisible,
            spaceEnabled = spaceUsedInSession,
            videoDone = videoDone,
            audioDone = micStopped && pendingAudioUploads.get() == 0,
            imuDone = imuStopped && pendingImuUploads.get() == 0,
        )
    }

    suspend fun startTime(
        scene: TimeScene?,
        partition: DataPartition,
        title: String,
        glassSid: String?,
        memoryType: MemoryType = MemoryType.TIME,
        sceneType: SpaceSceneType? = null,
    ): String {
        val id = repo.startSession(memoryType, scene, partition, title, sceneType = sceneType)
        EchoLog.i("创建会话 session=$id memoryType=$memoryType scene=$scene sceneType=$sceneType partition=$partition glassSid=$glassSid")
        sessionId = id
        this.glassSid = glassSid
        videoDone = false
        micStopped = false
        imuStopped = false
        spaceUsedInSession = false
        uploadBarVisible = true
        mp4HeaderCache = null
        headerPatchReceived = false
        pendingSpace = null
        lastVideoChunkAtNanos = 0L
        pendingVideoUploads.set(0)
        pendingAudioUploads.set(0)
        pendingImuUploads.set(0)
        publishUploadStatus()
        collectImu(id)
        collectVideo(id)
        if (memoryType == MemoryType.TIME) {
            startMic(id)
            glasses.startTimeRecording(scene ?: TimeScene.MEETING, partition)
        } else {
            micStopped = true // SPACE 不采音频
            glasses.startTimeRecording(scene ?: TimeScene.MEETING, partition)
        }
        return id
    }

    private fun collectImu(id: String) {
        imuJob = scope.launch {
            glasses.imuFlow.collect { imu ->
                if (!spaceUsedInSession) { spaceUsedInSession = true; publishUploadStatus() }
                val chunk = synchronized(imuBatchLock) {
                    pendingImuBatch += imu
                    if (pendingImuBatch.size >= 25) pendingImuBatch.toList().also { pendingImuBatch.clear() } else null
                }
                if (chunk != null) uploadImuTracked { uploadImuBatch(id, chunk) }
            }
        }
    }

    /**
     * 视频分片必须严格按 index 顺序串行 POST，后台按到达顺序 append 再在收到末片时 rename；
     * 因此这里在 collect 内部直接 await 每次上传（而非像音频/IMU 那样用 [uploadTracked] 并发甩出去），
     * 否则并发乱序会导致 video_end 抢在前面分片写完之前触发过早 rename，成片被截断。
     *
     * 同时:
     * - idx=0 分片缓存到 [mp4HeaderCache](含 ftyp+moov MP4 头,用于旁路 SPACE 会话本地文件初始化);
     * - 若 [inlineSpace] 活跃,把当前分片同步 append 到其本地缓存文件。
     */
    private fun collectVideo(id: String) {
        videoJob = scope.launch {
            glasses.videoChunkFlow.collect { chunk ->
                when (chunk) {
                    is VideoChunk.Data -> {
                        if (glassSid != null && chunk.streamId != glassSid) return@collect
                        markVideoChunkReceived()
                        if (chunk.index == 0) mp4HeaderCache = chunk.bytes
                        appendInlineSpace(chunk.bytes)
                        uploadVideoSequential { repo.uploadVideoChunk(id, chunk.index, false, null, chunk.bytes) }
                    }
                    is VideoChunk.Patch -> {
                        if (glassSid != null && chunk.streamId != glassSid) return@collect
                        markVideoChunkReceived()
                        EchoLog.i("收到 header patch offset=${chunk.offset} size=${chunk.bytes.size}")
                        // 先把 patch 写入本地 SPACE 缓存，再释放等待方；否则 stopSpace
                        // 可能看到标志后抢先关闭并上传未写入 moov 的文件。
                        patchInlineSpace(chunk.offset, chunk.bytes)
                        headerPatchReceived = true
                        uploadVideoSequential { repo.patchVideoHeader(id, chunk.offset, chunk.bytes) }
                    }
                    is VideoChunk.End -> {
                        if (glassSid != null && chunk.streamId != glassSid) return@collect
                        markVideoChunkReceived()
                        uploadVideoSequential { repo.uploadVideoChunk(id, -1, true, chunk.filename, ByteArray(0)) }
                        videoDone = true
                        publishUploadStatus()
                        EchoLog.i("视频分片接收完毕 session=$id filename=${chunk.filename}")
                    }
                }
            }
        }
    }

    private fun markVideoChunkReceived() {
        lastVideoChunkAtNanos = System.nanoTime()
    }

    /** 把分片 append 到旁路 SPACE 本地缓存(若活跃)。 */
    private fun appendInlineSpace(bytes: ByteArray) {
        val s = inlineSpace ?: pendingSpace ?: return
        runCatching {
            synchronized(s) {
                appendVideoChunk(s.raf, bytes)
            }
        }.onFailure { EchoLog.e("旁路 SPACE 缓存写入失败: ${it.message}", it) }
    }

    /** 把 patch 应用到旁路 SPACE 本地缓存(若活跃)。 */
    private fun patchInlineSpace(offset: Long, bytes: ByteArray) {
        val s = inlineSpace ?: pendingSpace ?: return
        runCatching {
            synchronized(s) {
                val fileLen = s.raf.length()
                EchoLog.i("旁路 SPACE 收到 patch offset=$offset len=${bytes.size} 当前文件长度=$fileLen session=${s.sessionId}")
                applyVideoPatch(s.raf, offset, bytes)
            }
        }.onFailure { EchoLog.e("旁路 SPACE 缓存 patch 失败: ${it.message}", it) }
    }

    private suspend fun uploadVideoSequential(block: suspend () -> Unit) {
        pendingUploads.incrementAndGet()
        pendingVideoUploads.incrementAndGet()
        try { block() } catch (e: Exception) { EchoLog.e("视频分片上传失败: ${e.message}", e) }
        finally {
            pendingUploads.decrementAndGet()
            pendingVideoUploads.decrementAndGet()
        }
    }

    /** 等待视频结束、patch 上传完成，并给乱序到达的尾部 chunk 留出落盘时间。 */
    private suspend fun waitForSpaceVideoReady(timeoutMs: Long): Boolean {
        return withTimeoutOrNull(timeoutMs) {
            while (true) {
                val lastChunkAt = lastVideoChunkAtNanos
                val quietEnough = lastChunkAt != 0L &&
                    System.nanoTime() - lastChunkAt >= SPACE_VIDEO_TAIL_SETTLE_NANOS
                if (canFinalizeSpace(headerPatchReceived, videoDone) &&
                    pendingVideoUploads.get() == 0 && quietEnough
                ) break
                delay(50)
            }
            true
        } ?: false
    }

    private fun startMic(id: String) {
        micJob = scope.launch {
            mic.audioFlow.collect { audio -> uploadAudioTracked { repo.uploadAudio(id, audio) } }
        }
        if (!mic.start()) EchoLog.w("手机麦克风启动失败，本次记忆将缺失音频 session=$id")
    }

    private fun uploadAudioTracked(block: suspend () -> Unit) {
        pendingUploads.incrementAndGet(); pendingAudioUploads.incrementAndGet()
        scope.launch {
            try { block() } catch (e: Exception) { EchoLog.e("音频上传失败: ${e.message}", e) }
            finally { pendingUploads.decrementAndGet(); pendingAudioUploads.decrementAndGet(); publishUploadStatus() }
        }
    }

    private fun uploadImuTracked(block: suspend () -> Unit) {
        pendingUploads.incrementAndGet(); pendingImuUploads.incrementAndGet()
        scope.launch {
            try { block() } catch (e: Exception) { EchoLog.e("IMU上传失败: ${e.message}", e) }
            finally { pendingUploads.decrementAndGet(); pendingImuUploads.decrementAndGet(); publishUploadStatus() }
        }
    }

    private suspend fun uploadImuBatch(id: String, samples: List<ImuSample>) {
        repo.uploadImuBatch(id, samples)
        EchoLog.i("IMU batch uploaded session=$id count=${samples.size}")
    }

    suspend fun stopAndComplete(): MemorySummary {
        val id = sessionId ?: throw IllegalStateException("No active session")
        // 若还有未结束的旁路 SPACE,先静默清理资源(不上传不 complete,避免 stopAndComplete 过长)。
        inlineSpace?.let { s ->
            inlineSpace = null
            runCatching { synchronized(s) { s.raf.close() } }
            runCatching { s.cacheFile.delete() }
            EchoLog.w("TIME 结束时仍有旁路 SPACE 未结束,已丢弃 session=${s.sessionId}")
        }
        glasses.stopRecording()
        mic.stop()

        var pendingSpaceVideoReady = pendingSpace == null
        withTimeoutOrNull(UPLOAD_DRAIN_TIMEOUT_MS) {
            delay(300) // 留出时间让麦克风尾块/眼镜尾部视频分片进入上传队列
            while (!videoDone || pendingUploads.get() > 0) delay(100)
            if (pendingSpace != null) {
                pendingSpaceVideoReady = waitForSpaceVideoReady(UPLOAD_DRAIN_TIMEOUT_MS)
            }
        } ?: EchoLog.w("等待视频/音频上传排空超时 session=$id videoDone=$videoDone pending=${pendingUploads.get()}")

        imuJob?.cancelAndJoin(); imuJob = null
        videoJob?.cancelAndJoin(); videoJob = null
        micJob?.cancelAndJoin(); micJob = null
        micStopped = true
        imuStopped = true

        // SPACE 可能已经在 UI 上结束，但要等整体 TIME 视频的最终 patch 到达后才能完成。
        pendingSpace?.let { space ->
            if (pendingSpaceVideoReady && canFinalizeSpace(headerPatchReceived, videoDone)) {
                finalizePendingSpace(space)
            } else {
                EchoLog.e("TIME 结束时仍未收到 header patch，保留 SPACE 缓存未上传 session=${space.sessionId}")
            }
        }

        val tailImu = synchronized(imuBatchLock) {
            pendingImuBatch.toList().also { pendingImuBatch.clear() }
        }
        if (tailImu.isNotEmpty()) uploadImuBatch(id, tailImu)
        publishUploadStatus() // 此时视频/音频/IMU 均已排空，各项应已全部转为"上传结束"

        val summary = repo.completeSession(id)
        val sidForGlass = glassSid ?: id
        runCatching { glasses.sendMemoryComplete(sidForGlass) }
        sessionId = null; glassSid = null
        scope.launch {
            delay(UPLOAD_BAR_LINGER_MS) // 让用户看到"上传结束"提示后再隐藏上传状态栏
            uploadBarVisible = false
            publishUploadStatus()
        }
        return summary
    }

    // --- 空间记忆(SPACE)录制 ---

    /**
     * 开启旁路 SPACE 录制。要求当前已在录 TIME(sessionId != null),因为视频源由眼镜推流,
     * phone 只能"搭车"把后续分片落本地,等 [stopSpace] 时把本地缓存作为独立视频上传。
     *
     * 若当前未在录 TIME,应改用 [startTime] 创建独立 SPACE 主会话(由 EchoApplication 根据
     * pendingSpaceSceneType 决定),此处不处理。
     */
    suspend fun startSpace(sceneType: SpaceSceneType, partition: DataPartition, title: String): String {
        check(sessionId != null) { "旁路 SPACE 需要先有 TIME 会话在录" }
        check(inlineSpace == null) { "旁路 SPACE 已在录制中" }
        val spaceSessionId = repo.startSession(
            MemoryType.SPACE, scene = null, partition = partition, title = title, sceneType = sceneType,
        )
        val cacheFile = File(cacheDir, "space_${spaceSessionId}.mp4")
        val raf = RandomAccessFile(cacheFile, "rw")
        // 写入之前缓存的 MP4 头(idx=0 分片),保证本地文件是完整可解析的 MP4。
        mp4HeaderCache?.let { raf.write(it) }
        inlineSpace = InlineSpaceSession(spaceSessionId, sceneType, cacheFile, raf)
        EchoLog.i("旁路 SPACE 已开启 session=$spaceSessionId sceneType=$sceneType cache=${cacheFile.absolutePath}")
        return spaceSessionId
    }

    /**
     * 结束旁路 SPACE 录制:关闭本地缓存,把本地文件按分片 POST 到 SPACE 会话,complete。
     * 返回 complete 后的 MemorySummary。
     */
    suspend fun stopSpace(): MemorySummary? {
        val s = inlineSpace ?: throw IllegalStateException("当前无旁路 SPACE 录制")
        s.closed = true
        inlineSpace = null
        pendingSpace = s

        // 等待眼镜端发送 header patch(真正的 moov box)，最多等待 3 秒。
        // 眼镜端在 STOP 后才发送 patch，用户可能在 patch 到达前就点击"结束空间记忆"。
        if (!headerPatchReceived) {
            EchoLog.w("等待 header patch 到达 session=${s.sessionId}")
            var waited = 0
            while (!headerPatchReceived && waited < 3000) {
                delay(100)
                waited += 100
            }
            if (!headerPatchReceived) {
                EchoLog.w("等待 header patch 超时，延迟 SPACE 上传到 TIME 结束 session=${s.sessionId}")
                return null
            } else {
                EchoLog.i("header patch 已到达，等待时长=${waited}ms session=${s.sessionId}")
            }
        }

        if (!waitForSpaceVideoReady(SPACE_VIDEO_READY_TIMEOUT_MS)) {
            EchoLog.w("等待视频结束或尾部分片排空超时，延迟 SPACE 上传到 TIME 结束 session=${s.sessionId}")
            return null
        }

        return finalizePendingSpace(s)
    }

    /** 仅在最终 patch 已写入缓存后关闭、上传并完成待处理 SPACE。 */
    private suspend fun finalizePendingSpace(s: InlineSpaceSession): MemorySummary {
        synchronized(s) {
            if (s.finalized) throw IllegalStateException("SPACE 会话已完成 session=${s.sessionId}")
            if (s.finalizing) throw IllegalStateException("SPACE 会话正在完成 session=${s.sessionId}")
            s.finalizing = true
        }

        try {
            synchronized(s) {
                s.raf.fd.sync()
                s.raf.close()
            }
            // 分片上传本地缓存(避免一次性读入内存)。逐 chunk 串行 POST。
            val filename = "space_${s.sessionId}.mp4"
            val buf = ByteArray(SPACE_UPLOAD_CHUNK_BYTES)
            s.cacheFile.inputStream().use { input ->
                var idx = 0
                while (true) {
                    val n = input.read(buf)
                    if (n <= 0) break
                    val bytes = if (n == buf.size) buf else buf.copyOf(n)
                    repo.uploadVideoChunk(s.sessionId, idx, isLast = false, filename = null, bytes = bytes)
                    idx++
                }
                // 末片:空字节 + isLast=true + filename,后端收到后 rename。
                repo.uploadVideoChunk(s.sessionId, -1, isLast = true, filename = filename, bytes = ByteArray(0))
            }
            EchoLog.i("旁路 SPACE 视频已上传 session=${s.sessionId} size=${s.cacheFile.length()} bytes")
            val summary = repo.completeSession(s.sessionId)
            synchronized(s) { s.finalized = true }
            if (pendingSpace === s) pendingSpace = null
            return summary
        } finally {
            synchronized(s) { s.finalizing = false }
            runCatching { s.raf.close() }
            runCatching { s.cacheFile.delete() }
        }
    }

    private companion object {
        const val UPLOAD_DRAIN_TIMEOUT_MS = 15_000L
        const val UPLOAD_BAR_LINGER_MS = 2_000L
        const val SPACE_VIDEO_READY_TIMEOUT_MS = 3_000L
        const val SPACE_VIDEO_TAIL_SETTLE_NANOS = 500_000_000L
        const val SPACE_UPLOAD_CHUNK_BYTES = 1 * 1024 * 1024 // 1MB
    }
}
