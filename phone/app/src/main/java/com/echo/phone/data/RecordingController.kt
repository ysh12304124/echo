package com.echo.phone.data

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import android.os.SystemClock
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
import java.nio.ByteBuffer
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
 * SPACE 时间标记：只记录开始/结束时间戳(相对 TIME 录制起点的毫秒),
 * TIME 结束后按范围从完整视频剪辑出 SPACE MP4 上传。
 */
private data class SpaceMark(
    val sessionId: String,
    val sceneType: SpaceSceneType,
    val startRelMs: Long,
    var endRelMs: Long? = null,
)

/**
 * 记忆录制编排：TIME 期间除了正常上传视频分片外，也把完整视频落到本地文件；
 * SPACE 只记录起止时间戳，TIME 结束后按时间范围重封装并上传独立的 SPACE MP4。
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
    @Volatile private var videoUploadFailed = false
    @Volatile private var micStopped = false
    @Volatile private var imuStopped = false
    @Volatile private var spaceUsedInSession = false
    @Volatile private var uploadBarVisible = false
    private val pendingUploads = AtomicInteger(0)
    private val pendingVideoUploads = AtomicInteger(0)
    private val pendingAudioUploads = AtomicInteger(0)
    private val pendingImuUploads = AtomicInteger(0)

    /** 标记是否已收到眼镜端的 header patch(真正的 moov box)。 */
    @Volatile private var headerPatchReceived: Boolean = false

    /** TIME 录制起点(elapsedRealtime)，用于计算 SPACE 相对时间戳。 */
    @Volatile private var recordingStartElapsedMs: Long = 0L

    /** 完整 TIME 视频本地落盘(Data append + Patch overwrite)，用于剪辑 SPACE 片段。 */
    private val timeFullLock = Any()
    @Volatile private var timeFullFile: File? = null
    @Volatile private var timeFullRaf: RandomAccessFile? = null

    /** 当前活跃的 SPACE(用户已开启但未结束)。 */
    @Volatile private var activeSpace: SpaceMark? = null

    /** 已结束但等待 TIME finalize 后剪辑上传的 SPACE。 */
    private val pendingSpaces: MutableList<SpaceMark> = mutableListOf()
    private val pendingSpacesLock = Any()

    private val _uploadStatus = MutableStateFlow(UploadStatus())
    val uploadStatus: StateFlow<UploadStatus> = _uploadStatus.asStateFlow()

    /** 当前是否有活跃的旁路 SPACE 录制(供 UI 显示"3D 记忆中"状态)。 */
    val isInlineSpaceActive: Boolean get() = activeSpace != null

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
        videoUploadFailed = false
        micStopped = false
        imuStopped = false
        spaceUsedInSession = false
        uploadBarVisible = true
        headerPatchReceived = false
        recordingStartElapsedMs = SystemClock.elapsedRealtime()
        activeSpace = null
        synchronized(pendingSpacesLock) { pendingSpaces.clear() }
        pendingVideoUploads.set(0)
        pendingAudioUploads.set(0)
        pendingImuUploads.set(0)
        // 打开本地完整视频文件（仅 TIME 类型才需要，SPACE 独立会话不剪辑）
        if (memoryType == MemoryType.TIME) openTimeFullFile(id)
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

    private fun openTimeFullFile(id: String) {
        synchronized(timeFullLock) {
            val f = File(cacheDir, "time_full_${id}.mp4")
            runCatching { f.delete() }
            timeFullFile = f
            timeFullRaf = RandomAccessFile(f, "rw")
            EchoLog.i("TIME 完整视频缓存已打开 path=${f.absolutePath}")
        }
    }

    private fun closeTimeFullFile() {
        synchronized(timeFullLock) {
            timeFullRaf?.let { raf ->
                runCatching { raf.fd.sync() }
                runCatching { raf.close() }
            }
            timeFullRaf = null
        }
    }

    private fun deleteTimeFullFile() {
        synchronized(timeFullLock) {
            timeFullFile?.let { runCatching { it.delete() } }
            timeFullFile = null
        }
    }

    private fun appendTimeFull(bytes: ByteArray) {
        synchronized(timeFullLock) {
            val raf = timeFullRaf ?: return
            runCatching {
                raf.seek(raf.length())
                raf.write(bytes)
            }.onFailure { EchoLog.e("TIME 完整视频写入失败: ${it.message}", it) }
        }
    }

    private fun patchTimeFull(offset: Long, bytes: ByteArray) {
        synchronized(timeFullLock) {
            val raf = timeFullRaf ?: return
            runCatching {
                raf.seek(offset)
                raf.write(bytes)
            }.onFailure { EchoLog.e("TIME 完整视频 patch 失败: ${it.message}", it) }
        }
    }

    private fun collectImu(id: String) {
        imuJob = scope.launch {
            glasses.imuFlow.collect { imu ->
                if (!spaceUsedInSession) { spaceUsedInSession = true; publishUploadStatus() }
                val chunk = synchronized(imuBatchLock) {
                    pendingImuBatch += imu
                    if (pendingImuBatch.size >= 25) pendingImuBatch.toList().also { pendingImuBatch.clear() } else null
                }
                if (chunk != null) {
                    uploadImuTracked { uploadImuBatch(id, chunk) }
                    // SPACE 用 IMU 判断重力方向,SPACE 活跃时同时上传到 SPACE session
                    val space = activeSpace
                    if (space != null) {
                        uploadImuTracked { uploadImuBatch(space.sessionId, chunk) }
                    }
                }
            }
        }
    }

    /**
     * 视频分片必须严格按 index 顺序串行 POST，后台按到达顺序 append 再在收到末片时 rename；
     * 因此这里在 collect 内部直接 await 每次上传（而非像音频/IMU 那样用 [uploadTracked] 并发甩出去），
     * 否则并发乱序会导致 video_end 抢在前面分片写完之前触发过早 rename，成片被截断。
     *
     * 同时把每个分片同步落到本地完整 TIME 视频文件(供后续 SPACE 剪辑使用)。
     */
    private fun collectVideo(id: String) {
        videoJob = scope.launch {
            glasses.videoChunkFlow.collect { chunk ->
                when (chunk) {
                    is VideoChunk.Data -> {
                        if (glassSid != null && chunk.streamId != glassSid) return@collect
                        appendTimeFull(chunk.bytes)
                        uploadVideoSequential { repo.uploadVideoChunk(id, chunk.index, false, null, chunk.bytes) }
                    }
                    is VideoChunk.Patch -> {
                        if (glassSid != null && chunk.streamId != glassSid) return@collect
                        EchoLog.i("收到 header patch offset=${chunk.offset} size=${chunk.bytes.size}")
                        patchTimeFull(chunk.offset, chunk.bytes)
                        if (uploadVideoSequential { repo.patchVideoHeader(id, chunk.offset, chunk.bytes) }) {
                            headerPatchReceived = true
                        }
                    }
                    is VideoChunk.End -> {
                        if (glassSid != null && chunk.streamId != glassSid) return@collect
                        if (uploadVideoSequential { repo.uploadVideoChunk(id, -1, true, chunk.filename, ByteArray(0)) }) {
                            videoDone = true
                            publishUploadStatus()
                            EchoLog.i("视频分片接收完毕 session=$id filename=${chunk.filename}")
                        }
                    }
                }
            }
        }
    }

    private suspend fun uploadVideoSequential(block: suspend () -> Unit): Boolean {
        pendingUploads.incrementAndGet()
        pendingVideoUploads.incrementAndGet()
        return try {
            block()
            true
        } catch (e: Exception) {
            videoUploadFailed = true
            EchoLog.e("视频分片上传失败: ${e.message}", e)
            false
        }
        finally {
            pendingUploads.decrementAndGet()
            pendingVideoUploads.decrementAndGet()
        }
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

        // 若还有未结束的 SPACE，视为在 TIME 结束时刻同时结束
        val closingSpace = activeSpace
        activeSpace?.let { mark ->
            mark.endRelMs = SystemClock.elapsedRealtime() - recordingStartElapsedMs
            synchronized(pendingSpacesLock) { pendingSpaces.add(mark) }
            activeSpace = null
            runCatching { glasses.setSpaceCapture(false) }
            EchoLog.w("TIME 结束时 SPACE 仍活跃,视为在此时结束 session=${mark.sessionId} end=${mark.endRelMs}ms")
        }

        glasses.stopRecording()
        mic.stop()

        // 等视频分片、patch 全部到齐并上传完成
        withTimeoutOrNull(UPLOAD_DRAIN_TIMEOUT_MS) {
            delay(300)
            while (!videoDone || !headerPatchReceived || pendingUploads.get() > 0) delay(100)
        } ?: EchoLog.w("等待视频/音频上传排空超时 session=$id videoDone=$videoDone patch=$headerPatchReceived pending=${pendingUploads.get()}")

        imuJob?.cancelAndJoin(); imuJob = null
        videoJob?.cancelAndJoin(); videoJob = null
        micJob?.cancelAndJoin(); micJob = null
        micStopped = true
        imuStopped = true

        if (!videoDone || !headerPatchReceived || videoUploadFailed) {
            closeTimeFullFile()
            deleteTimeFullFile()
            error(
                "眼镜视频未完整上传，已阻止提交 session=$id " +
                    "videoDone=$videoDone patch=$headerPatchReceived failed=$videoUploadFailed"
            )
        }

        // 关闭本地完整视频文件，准备剪辑
        closeTimeFullFile()

        // 处理所有 pending SPACE：按时间范围剪辑并上传
        val marks = synchronized(pendingSpacesLock) { pendingSpaces.toList().also { pendingSpaces.clear() } }
        for (mark in marks) {
            runCatching { clipAndUploadSpace(mark) }
                .onFailure { EchoLog.e("SPACE 剪辑/上传失败 session=${mark.sessionId}: ${it.message}", it) }
        }

        // 清理本地完整视频缓存
        deleteTimeFullFile()

        val tailImu = synchronized(imuBatchLock) {
            pendingImuBatch.toList().also { pendingImuBatch.clear() }
        }
        EchoLog.i("tailImu.size=${tailImu.size} closingSpace=${closingSpace?.sessionId}")
        if (tailImu.isNotEmpty()) {
            // SPACE 若在 TIME 结束时刻仍活跃,尾部 IMU 先给 SPACE
            closingSpace?.let {
                runCatching { uploadImuBatch(it.sessionId, tailImu) }
                    .onFailure { e -> EchoLog.e("尾部 IMU 上传 SPACE 失败: ${e.message}", e) }
            }
            uploadImuBatch(id, tailImu)
        }
        publishUploadStatus()

        val summary = repo.completeSession(id)
        val sidForGlass = glassSid ?: id
        runCatching { glasses.sendMemoryComplete(sidForGlass) }
        sessionId = null; glassSid = null
        scope.launch {
            delay(UPLOAD_BAR_LINGER_MS)
            uploadBarVisible = false
            publishUploadStatus()
        }
        return summary
    }

    // --- 空间记忆(SPACE)录制 ---

    /**
     * 开启旁路 SPACE 录制。要求当前已在录 TIME(sessionId != null),只记录起始时间戳。
     * 真正的视频在 TIME 结束后按时间范围剪辑上传。
     */
    suspend fun startSpace(sceneType: SpaceSceneType, partition: DataPartition, title: String): String {
        check(sessionId != null) { "旁路 SPACE 需要先有 TIME 会话在录" }
        check(activeSpace == null) { "旁路 SPACE 已在录制中" }
        val spaceSessionId = repo.startSession(
            MemoryType.SPACE, scene = null, partition = partition, title = title, sceneType = sceneType,
        )
        val startRelMs = SystemClock.elapsedRealtime() - recordingStartElapsedMs
        activeSpace = SpaceMark(spaceSessionId, sceneType, startRelMs)
        // 通知眼镜端启用 IMU 采集（用于点云重力方向矫正）
        runCatching { glasses.setSpaceCapture(true) }
        EchoLog.i("旁路 SPACE 已开启 session=$spaceSessionId sceneType=$sceneType startRelMs=${startRelMs}")
        return spaceSessionId
    }

    /**
     * 结束旁路 SPACE 录制:只记录结束时间戳，加入待处理列表。
     * 实际的视频剪辑、上传、complete 会延后到 [stopAndComplete] 阶段执行。
     */
    suspend fun stopSpace(): MemorySummary? {
        val mark = activeSpace ?: throw IllegalStateException("当前无旁路 SPACE 录制")
        mark.endRelMs = SystemClock.elapsedRealtime() - recordingStartElapsedMs
        // IMU 是 1Hz 采样,batch=25 才 upload,SPACE 短于 25s 时 pending 里的样本从未刷到 SPACE。
        // 在 SPACE 结束时把当前 pending 样本立刻同步 flush 到 SPACE session。
        val pending = synchronized(imuBatchLock) { pendingImuBatch.toList() }
        EchoLog.i("旁路 SPACE 准备结束 session=${mark.sessionId} pending=${pending.size}")
        if (pending.isNotEmpty()) {
            runCatching { uploadImuBatch(mark.sessionId, pending) }
                .onFailure { EchoLog.e("SPACE IMU flush 失败 session=${mark.sessionId}: ${it.message}", it) }
        }
        synchronized(pendingSpacesLock) { pendingSpaces.add(mark) }
        activeSpace = null
        // 通知眼镜端关闭 IMU 采集
        runCatching { glasses.setSpaceCapture(false) }
        EchoLog.i("旁路 SPACE 已结束 session=${mark.sessionId} start=${mark.startRelMs}ms end=${mark.endRelMs}ms flush=${pending.size} 待 TIME 结束后剪辑上传")
        return null
    }

    /** 用 MediaExtractor+MediaMuxer 按时间范围从完整 TIME 视频剪出 SPACE MP4,分片上传并 complete。 */
    private suspend fun clipAndUploadSpace(mark: SpaceMark) {
        val sourceFile = timeFullFile ?: run {
            EchoLog.e("剪辑失败:TIME 完整视频不存在 session=${mark.sessionId}")
            return
        }
        val endRelMs = mark.endRelMs ?: run {
            EchoLog.e("剪辑失败:SPACE 无结束时间 session=${mark.sessionId}")
            return
        }
        val outFile = File(cacheDir, "space_${mark.sessionId}.mp4")
        runCatching { outFile.delete() }

        val startUs = mark.startRelMs * 1000L
        val endUs = endRelMs * 1000L

        EchoLog.i("开始剪辑 SPACE session=${mark.sessionId} source=${sourceFile.absolutePath} startUs=$startUs endUs=$endUs")

        val ok = runCatching {
            clipMp4ByTimeRange(sourceFile, outFile, startUs, endUs)
        }.onFailure { EchoLog.e("MediaMuxer 剪辑失败: ${it.message}", it) }.getOrDefault(false)

        if (!ok || !outFile.exists() || outFile.length() < 1024) {
            EchoLog.e("SPACE 剪辑输出无效 session=${mark.sessionId} exists=${outFile.exists()} size=${if (outFile.exists()) outFile.length() else -1}")
            runCatching { outFile.delete() }
            return
        }

        EchoLog.i("SPACE 剪辑完成 session=${mark.sessionId} outSize=${outFile.length()} bytes")

        // 分片上传本地剪辑结果
        val filename = "space_${mark.sessionId}.mp4"
        val buf = ByteArray(SPACE_UPLOAD_CHUNK_BYTES)
        outFile.inputStream().use { input ->
            var idx = 0
            while (true) {
                val n = input.read(buf)
                if (n <= 0) break
                val bytes = if (n == buf.size) buf else buf.copyOf(n)
                repo.uploadVideoChunk(mark.sessionId, idx, isLast = false, filename = null, bytes = bytes)
                idx++
            }
            repo.uploadVideoChunk(mark.sessionId, -1, isLast = true, filename = filename, bytes = ByteArray(0))
        }
        EchoLog.i("SPACE 视频已上传 session=${mark.sessionId}")

        repo.completeSession(mark.sessionId)
        runCatching { outFile.delete() }
    }

    /**
     * 用 MediaExtractor + MediaMuxer 按时间范围重新封装 MP4。
     * 只拷贝视频轨(SPACE 不需要音频)，从 startUs 之前的最近 sync frame 开始，直到 endUs。
     */
    private fun clipMp4ByTimeRange(src: File, dst: File, startUs: Long, endUs: Long): Boolean {
        val extractor = MediaExtractor()
        val muxer: MediaMuxer
        try {
            extractor.setDataSource(src.absolutePath)
        } catch (e: Exception) {
            EchoLog.e("MediaExtractor 打开源文件失败: ${e.message}", e)
            return false
        }

        // 选择第一条视频轨
        var videoTrack = -1
        var videoFormat: MediaFormat? = null
        for (i in 0 until extractor.trackCount) {
            val fmt = extractor.getTrackFormat(i)
            val mime = fmt.getString(MediaFormat.KEY_MIME) ?: continue
            if (mime.startsWith("video/")) {
                videoTrack = i
                videoFormat = fmt
                break
            }
        }
        if (videoTrack < 0 || videoFormat == null) {
            EchoLog.e("源视频无 video track")
            extractor.release()
            return false
        }
        extractor.selectTrack(videoTrack)

        try {
            muxer = MediaMuxer(dst.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
        } catch (e: Exception) {
            EchoLog.e("MediaMuxer 创建失败: ${e.message}", e)
            extractor.release()
            return false
        }

        val muxerVideoTrack = muxer.addTrack(videoFormat)
        muxer.start()

        // 从 startUs 之前的最近关键帧开始
        extractor.seekTo(startUs, MediaExtractor.SEEK_TO_PREVIOUS_SYNC)
        val maxBufSize = videoFormat.getInteger(MediaFormat.KEY_MAX_INPUT_SIZE).takeIf { it > 0 } ?: (1024 * 1024)
        val buffer = ByteBuffer.allocate(maxBufSize)
        val info = MediaCodec.BufferInfo()
        var wroteAny = false

        try {
            while (true) {
                info.offset = 0
                val sampleSize = extractor.readSampleData(buffer, 0)
                if (sampleSize < 0) break
                val sampleTime = extractor.sampleTime
                if (sampleTime > endUs) break
                info.size = sampleSize
                info.presentationTimeUs = sampleTime
                info.flags = extractor.sampleFlags
                muxer.writeSampleData(muxerVideoTrack, buffer, info)
                wroteAny = true
                if (!extractor.advance()) break
            }
        } catch (e: Exception) {
            EchoLog.e("剪辑写入失败: ${e.message}", e)
        } finally {
            runCatching { muxer.stop() }
            runCatching { muxer.release() }
            runCatching { extractor.release() }
        }

        return wroteAny
    }

    private companion object {
        const val UPLOAD_DRAIN_TIMEOUT_MS = 15_000L
        const val UPLOAD_BAR_LINGER_MS = 2_000L
        const val SPACE_UPLOAD_CHUNK_BYTES = 1 * 1024 * 1024 // 1MB
    }
}
