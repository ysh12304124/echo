package com.echo.phone.data.glasses

import com.echo.phone.domain.*
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlin.random.Random

/** 眼镜连接/会话过程中的可读错误，供 UI 展示给用户。 */
class GlassesConnectionException(message: String) : Exception(message)

/**
 * 与眼镜 SDK 解耦的连接接口，便于后续更换不同眼镜设备。
 *
 * 真机实现见 [com.echo.phone.data.glasses.cxr.CxrGlassesConnection]（Rokid CXR-L）。
 * 眼镜端边录制视频边分片经 rk_custom_key 推送，手机不落地直接转发后台，见 [videoChunkFlow]；
 * IMU 数据（空间记忆开启时）见 [imuFlow]；场景 START/STOP 指令见 [commands]。
 */
interface GlassesConnection {
    val connectionState: StateFlow<GlassesConnectionState>
    val deviceStatus: StateFlow<DeviceStatus>
    val videoChunkFlow: Flow<VideoChunk>
    val imuFlow: Flow<ImuSample>

    /** 眼镜端记忆控制指令流（选择场景后启动/再次点击停止，由眼镜端 App 上报）。 */
    val commands: Flow<GlassCommand>

    suspend fun connect()
    suspend fun disconnect()
    suspend fun startTimeRecording(scene: TimeScene, partition: DataPartition)
    suspend fun stopRecording()

    /** 后台 complete 成功后通知眼镜端记忆已完成（眼镜端据此可清理本地视频，当前阶段仅记录日志）。 */
    suspend fun sendMemoryComplete(sid: String)
}

/**
 * Mock 实现，用于无真机时开发和测试。
 *
 * 连接后按固定节奏产生合成视频分片，使离线也能跑通"边录边传→后台存储"全链路。
 */
class MockGlassesConnection(
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Default),
) : GlassesConnection {
    private val _connectionState = MutableStateFlow(GlassesConnectionState.DISCONNECTED)
    override val connectionState = _connectionState.asStateFlow()

    private val _deviceStatus = MutableStateFlow(DeviceStatus(connected = false))
    override val deviceStatus = _deviceStatus.asStateFlow()

    private val _videoChunkFlow = MutableSharedFlow<VideoChunk>(extraBufferCapacity = 64)
    override val videoChunkFlow = _videoChunkFlow.asSharedFlow()

    private val _imuFlow = MutableSharedFlow<ImuSample>(extraBufferCapacity = 128)
    override val imuFlow = _imuFlow.asSharedFlow()

    private val _commands = MutableSharedFlow<GlassCommand>(extraBufferCapacity = 8)
    override val commands = _commands.asSharedFlow()

    private var videoJob: Job? = null
    private var currentSid: String? = null

    override suspend fun connect() {
        _connectionState.value = GlassesConnectionState.CONNECTING
        _connectionState.value = GlassesConnectionState.CONNECTED
        _deviceStatus.value = DeviceStatus(connected = true, batteryPercent = 85)
    }

    override suspend fun disconnect() {
        stopSynthetic()
        _connectionState.value = GlassesConnectionState.DISCONNECTED
        _deviceStatus.value = DeviceStatus(connected = false)
    }

    override suspend fun startTimeRecording(scene: TimeScene, partition: DataPartition) {
        _connectionState.value = GlassesConnectionState.RECORDING
        _deviceStatus.value = _deviceStatus.value.copy(isRecordingTime = true)
        startSynthetic()
    }

    override suspend fun stopRecording() {
        _deviceStatus.value = _deviceStatus.value.copy(isRecordingTime = false)
        stopSynthetic()
        _connectionState.value = GlassesConnectionState.CONNECTED
    }

    override suspend fun sendMemoryComplete(sid: String) {}

    /** 测试注入：模拟眼镜端下发记忆控制指令。 */
    fun emitCommand(command: GlassCommand) {
        _commands.tryEmit(command)
    }

    private fun startSynthetic() {
        if (videoJob != null) return
        val sid = "mock-${System.currentTimeMillis()}"
        currentSid = sid
        videoJob = scope.launch {
            var idx = 0
            while (true) {
                _videoChunkFlow.tryEmit(VideoChunk.Data(sid, idx++, ByteArray(4096) { Random.nextInt().toByte() }))
                delay(800)
            }
        }
    }

    private fun stopSynthetic() {
        val sid = currentSid ?: return
        videoJob?.cancel(); videoJob = null
        _videoChunkFlow.tryEmit(VideoChunk.End(sid, "mock_end.mp4"))
        currentSid = null
    }
}
