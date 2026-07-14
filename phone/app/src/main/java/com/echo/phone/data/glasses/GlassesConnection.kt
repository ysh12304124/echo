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
 * 采集（音频 PCM、拍照 JPEG）由眼镜固件/SDK 经 CXR-L 送达手机后，以 [frameFlow]/[audioFlow] 暴露；
 * 眼镜物理按键经 [keyEvents] 暴露。
 */
interface GlassesConnection {
    val connectionState: StateFlow<GlassesConnectionState>
    val deviceStatus: StateFlow<DeviceStatus>
    val frameFlow: Flow<MediaFrame>
    val audioFlow: Flow<MediaAudio>
    val imuFlow: Flow<ImuSample>

    /** 眼镜端记忆控制指令流（选择场景后启动/再次点击停止，由眼镜端 App 上报）。 */
    val commands: Flow<GlassCommand>

    suspend fun connect()
    suspend fun disconnect()
    suspend fun startTimeRecording(scene: TimeScene, partition: DataPartition)
    suspend fun startSpaceRecording()
    suspend fun pauseRecording()
    suspend fun resumeRecording()
    suspend fun stopRecording(sessionType: MemoryType)
    /** 发送录制引导文案到眼镜（如请保持物体位于视线中心）。 */
    suspend fun sendGlassGuide(text: String)

    /** 发送质量反馈到眼镜（如画面模糊，请保持稳定）。 */
    suspend fun sendGlassFeedback(text: String)

    /** 发送回环完成通知到眼镜。 */
    suspend fun sendGlassLoopDone(angle: Float)

    suspend fun markKeyMoment()
}

/**
 * Mock 实现，用于无真机时开发和测试。
 *
 * 连接后按固定节奏产生合成关键帧与音频块，使离线也能跑通"边采边传→后台处理→查询"全链路。
 */
class MockGlassesConnection(
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Default),
) : GlassesConnection {
    private val _connectionState = MutableStateFlow(GlassesConnectionState.DISCONNECTED)
    override val connectionState = _connectionState.asStateFlow()

    private val _deviceStatus = MutableStateFlow(DeviceStatus(connected = false))
    override val deviceStatus = _deviceStatus.asStateFlow()

    private val _frameFlow = MutableSharedFlow<MediaFrame>(extraBufferCapacity = 64)
    override val frameFlow = _frameFlow.asSharedFlow()

    private val _audioFlow = MutableSharedFlow<MediaAudio>(extraBufferCapacity = 64)
    override val audioFlow = _audioFlow.asSharedFlow()

    private val _imuFlow = MutableSharedFlow<ImuSample>(extraBufferCapacity = 128)
    override val imuFlow = _imuFlow.asSharedFlow()

    private val _commands = MutableSharedFlow<GlassCommand>(extraBufferCapacity = 8)
    override val commands = _commands.asSharedFlow()

    private var frameJob: Job? = null
    private var audioJob: Job? = null
    private var paused = false

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
        startSynthetic(withAudio = true)
    }

    override suspend fun startSpaceRecording() {
        _deviceStatus.value = _deviceStatus.value.copy(isRecordingSpace = true)
        startSynthetic(withAudio = false)
    }

    override suspend fun pauseRecording() {
        paused = true
        _connectionState.value = GlassesConnectionState.CONNECTED
    }

    override suspend fun resumeRecording() {
        paused = false
        _connectionState.value = GlassesConnectionState.RECORDING
    }

    override suspend fun stopRecording(sessionType: MemoryType) {
        when (sessionType) {
            MemoryType.TIME -> _deviceStatus.value = _deviceStatus.value.copy(isRecordingTime = false)
            MemoryType.SPACE -> _deviceStatus.value = _deviceStatus.value.copy(isRecordingSpace = false)
        }
        if (!_deviceStatus.value.isRecordingTime && !_deviceStatus.value.isRecordingSpace) {
            stopSynthetic()
            _connectionState.value = GlassesConnectionState.CONNECTED
        }
    }

    override suspend fun markKeyMoment() {
        _frameFlow.tryEmit(MediaFrame(syntheticJpeg(true), System.currentTimeMillis(), true))
    }

    override suspend fun sendGlassGuide(text: String) {}

    override suspend fun sendGlassFeedback(text: String) {}

    override suspend fun sendGlassLoopDone(angle: Float) {}

    /** 测试注入：模拟眼镜端下发记忆控制指令。 */
    fun emitCommand(command: GlassCommand) {
        _commands.tryEmit(command)
    }

    private fun startSynthetic(withAudio: Boolean) {
        paused = false
        if (frameJob == null) {
            frameJob = scope.launch {
                while (true) {
                    if (!paused) _frameFlow.tryEmit(
                        MediaFrame(syntheticJpeg(false), System.currentTimeMillis()),
                    )
                    delay(4000)
                }
            }
        }
        if (withAudio && audioJob == null) {
            audioJob = scope.launch {
                while (true) {
                    if (!paused) _audioFlow.tryEmit(
                        MediaAudio(ByteArray(32000) { Random.nextInt().toByte() }, System.currentTimeMillis()),
                    )
                    delay(1000)
                }
            }
        }
    }

    private fun stopSynthetic() {
        frameJob?.cancel(); frameJob = null
        audioJob?.cancel(); audioJob = null
    }

    // 一个最小的合成 JPEG（有效头 + 占位数据），便于后台按 JPEG 处理。
    private fun syntheticJpeg(keyMoment: Boolean): ByteArray {
        val header = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte(), 0xE0.toByte())
        val body = ByteArray(if (keyMoment) 2048 else 1024) { Random.nextInt().toByte() }
        val tail = byteArrayOf(0xFF.toByte(), 0xD9.toByte())
        return header + body + tail
    }
}
