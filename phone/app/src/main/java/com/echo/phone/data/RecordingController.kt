package com.echo.phone.data

import com.echo.phone.data.glasses.GlassesConnection
import com.echo.phone.data.spatial.PoseLoopDetector
import com.echo.phone.domain.*
import com.echo.phone.util.EchoLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

class RecordingController(
    private val repo: EchoRepository,
    private val glasses: GlassesConnection,
    private val scope: CoroutineScope,
) {
    private var sessionId: String? = null
    private var memoryType: MemoryType = MemoryType.TIME
    private var imuJob: Job? = null
    private var lastImuSample: ImuSample? = null
    private var poseLoopDetector: PoseLoopDetector? = null
    private val imuBatchLock = Any()
    private val pendingImuBatch = mutableListOf<ImuSample>()

    val currentSessionId: String? get() = sessionId

    suspend fun startTime(scene: TimeScene, partition: DataPartition, title: String): String {
        val id = repo.startSession(MemoryType.TIME, scene, partition, title)
        EchoLog.i("创建会话 session=$id scene=$scene partition=$partition")
        sessionId = id
        memoryType = MemoryType.TIME
        glasses.startTimeRecording(scene, partition)
        return id
    }

    suspend fun startSpace(spaceType: SpaceType, partition: DataPartition, title: String): String {
        val id = repo.startSession(MemoryType.SPACE, null, partition, title)
        EchoLog.i("创建空间会话 session=$id spaceType=$spaceType")
        sessionId = id
        memoryType = MemoryType.SPACE
        poseLoopDetector = PoseLoopDetector()
        collectImu()
        glasses.startSpaceRecording()
        val guide = when (spaceType) {
            SpaceType.SINGLE_OBJECT -> "请保持物体位于视线中心，360度绕物体记忆"
            SpaceType.LARGE_SCENE -> "请绕场景完整走一圈记忆"
        }
        glasses.sendGlassGuide(guide)
        return id
    }

    private fun collectImu() {
        val id = sessionId ?: return
        imuJob = scope.launch {
            glasses.imuFlow.collect { imu ->
                lastImuSample = imu
                poseLoopDetector?.updateImu(imu)
                val chunk = synchronized(imuBatchLock) {
                    pendingImuBatch += imu
                    if (pendingImuBatch.size >= 25) {
                        pendingImuBatch.toList().also { pendingImuBatch.clear() }
                    } else null
                }
                if (chunk != null) scope.launch { uploadImuBatch(id, chunk) }
            }
        }
    }

    private suspend fun uploadImuBatch(id: String, samples: List<ImuSample>) {
        try {
            repo.uploadImuBatch(id, samples)
            EchoLog.i("IMU batch uploaded session=$id count=${samples.size}")
        } catch (e: Exception) {
            EchoLog.e("IMU upload failed session=$id: ${e.message}", e)
        }
    }

    suspend fun pause() = glasses.pauseRecording()
    suspend fun resume() = glasses.resumeRecording()

    suspend fun stopAndComplete(): MemorySummary {
        val id = sessionId ?: throw IllegalStateException("No active session")
        glasses.stopRecording(memoryType)
        imuJob?.cancelAndJoin(); imuJob = null
        val tailImu = synchronized(imuBatchLock) {
            pendingImuBatch.toList().also { pendingImuBatch.clear() }
        }
        if (tailImu.isNotEmpty()) uploadImuBatch(id, tailImu)
        poseLoopDetector?.reset()
        poseLoopDetector = null
        val summary = repo.completeSession(id)
        sessionId = null
        return summary
    }
}
