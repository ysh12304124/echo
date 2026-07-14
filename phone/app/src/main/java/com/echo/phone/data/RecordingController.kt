package com.echo.phone.data

import com.echo.phone.data.glasses.GlassesConnection
import com.echo.phone.domain.*
import com.echo.phone.util.EchoLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.atomic.AtomicInteger

class RecordingController(
    private val repo: EchoRepository,
    private val glasses: GlassesConnection,
    private val scope: CoroutineScope,
    private val frameFilter: FrameFilter = SimpleFrameFilter(),
) {
    private var sessionId: String? = null
    private var memoryType: MemoryType = MemoryType.TIME
    private var frameJob: Job? = null
    private var audioJob: Job? = null
    private var imuJob: Job? = null
    private var qualityJob: Job? = null
    private val phoneMic = PhoneMicRecorder()
    private val qualityAnalyzer = PhotoQualityAnalyzer()
    private var lastImuSample: ImuSample? = null

    private val pendingUploads = AtomicInteger(0)

    val currentSessionId: String? get() = sessionId

    private companion object {
        const val UPLOAD_DRAIN_TIMEOUT_MS = 8_000L
    }

    suspend fun startTime(scene: TimeScene, partition: DataPartition, title: String): String {
        val id = repo.startSession(MemoryType.TIME, scene, partition, title)
        EchoLog.i("已在后台创建会话 session=$id scene=$scene partition=$partition")
        sessionId = id
        memoryType = MemoryType.TIME
        collectMedia(uploadAudio = true)
        phoneMic.start()
        glasses.startTimeRecording(scene, partition)
        return id
    }

    suspend fun startSpace(spaceType: SpaceType, partition: DataPartition, title: String): String {
        val id = repo.startSession(MemoryType.SPACE, null, partition, title)
        EchoLog.i("已在后台创建空间会话 session=$id spaceType=$spaceType")
        sessionId = id
        memoryType = MemoryType.SPACE
        collectMedia(uploadAudio = false)
        collectImu()
        collectQuality()
        glasses.startSpaceRecording()
        // 发送引导文案到眼镜
        val guide = when (spaceType) {
            SpaceType.SINGLE_OBJECT -> "请保持物体位于视线中心，360度绕物体记忆"
            SpaceType.LARGE_SCENE -> "请绕场景完整走一圈记忆"
        }
        glasses.sendGlassGuide(guide)
        return id
    }

    private fun collectMedia(uploadAudio: Boolean) {
        val id = sessionId ?: return
        frameJob = scope.launch {
            glasses.frameFlow.collect { frame ->
                if (frame.data.isEmpty()) return@collect
                if (!(frame.isKeyMoment || frameFilter.shouldKeep(frame))) return@collect
                pendingUploads.incrementAndGet()
                try {
                    EchoLog.i("上传帧到后台 session=$id bytes=${frame.data.size} key=${frame.isKeyMoment}")
                    repo.uploadFrame(id, frame)
                    EchoLog.i("帧上传成功 session=$id")
                } catch (e: Exception) {
                    EchoLog.e("帧上传失败 session=$id: ${e.message}", e)
                } finally {
                    pendingUploads.decrementAndGet()
                }
            }
        }
        if (uploadAudio) {
            audioJob = scope.launch {
                phoneMic.audioFlow.collect { audio ->
                    pendingUploads.incrementAndGet()
                    try {
                        EchoLog.i("上传音频到后台 session=$id bytes=${audio.data.size}")
                        repo.uploadAudio(id, audio)
                        EchoLog.i("音频上传成功 session=$id")
                    } catch (e: Exception) {
                        EchoLog.e("音频上传失败 session=$id: ${e.message}", e)
                    } finally {
                        pendingUploads.decrementAndGet()
                    }
                }
            }
        }
    }

    private fun collectImu() {
        val id = sessionId ?: return
        imuJob = scope.launch {
            val batch = mutableListOf<ImuSample>()
            glasses.imuFlow.collect { imu ->
                lastImuSample = imu
                batch.add(imu)
                if (batch.size >= 25) {
                    val chunk = batch.toList()
                    batch.clear()
                    try { repo.uploadImuBatch(id, chunk) }
                    catch (e: Exception) { EchoLog.e("IMU 批上传失败 session=$id: ${e.message}", e) }
                }
            }
            if (batch.isNotEmpty()) {
                try { repo.uploadImuBatch(id, batch.toList()) }
                catch (e: Exception) { EchoLog.e("IMU 尾部批上传失败 session=$id: ${e.message}", e) }
            }
        }
    }

    /** 照片质量实时分析：每收到一帧分析一次，不合格则反馈到眼镜。 */
    private fun collectQuality() {
        qualityJob = scope.launch {
            glasses.frameFlow.collect { frame ->
                if (frame.data.isEmpty()) return@collect
                val imgResult = qualityAnalyzer.analyzeImage(frame.data)
                val motionResult = lastImuSample?.let {
                    qualityAnalyzer.analyzeMotion(it.gx, it.gy, it.gz, it.timestampMs)
                } ?: QualityResult()
                val feedback = qualityAnalyzer.evaluate(imgResult, motionResult)
                if (feedback != null) {
                    glasses.sendGlassFeedback(feedback)
                    EchoLog.i("质量反馈发送到眼镜: $feedback")
                }
            }
        }
    }

    suspend fun pause() = glasses.pauseRecording()
    suspend fun resume() = glasses.resumeRecording()
    suspend fun markKeyMoment() = glasses.markKeyMoment()

    suspend fun stopAndComplete(): MemorySummary {
        val id = sessionId ?: throw IllegalStateException("没有进行中的录制")
        glasses.stopRecording(memoryType)
        if (memoryType == MemoryType.TIME) phoneMic.stop()
        withTimeoutOrNull(UPLOAD_DRAIN_TIMEOUT_MS) {
            delay(400)
            while (pendingUploads.get() > 0) delay(50)
        }
        val remaining = pendingUploads.get()
        if (remaining > 0) {
            EchoLog.w("结束时仍有 $remaining 个上传未完成(已达排空超时 ${UPLOAD_DRAIN_TIMEOUT_MS}ms)，继续结束")
        } else {
            EchoLog.i("剩余音视频已全部上传完成，开始结束会话 session=$id")
        }
        qualityJob?.cancel(); qualityJob?.join()
        imuJob?.cancel(); imuJob?.join()
        frameJob?.cancel(); frameJob?.join()
        audioJob?.cancel(); audioJob?.join()
        qualityJob = null; imuJob = null; frameJob = null; audioJob = null
        val summary = repo.completeSession(id)
        sessionId = null
        return summary
    }
}
