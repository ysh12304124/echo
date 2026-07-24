package com.echo.phone

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import androidx.core.app.NotificationCompat
import com.echo.phone.data.EchoRepository
import com.echo.phone.data.RecordingController
import com.echo.phone.data.api.ApiClient
import com.echo.phone.data.glasses.GlassesConnection
import com.echo.phone.data.glasses.MockGlassesConnection
import com.echo.phone.data.glasses.cxr.CxrGlassesConnection
import com.echo.phone.domain.DataPartition
import com.echo.phone.domain.GlassCommand
import com.echo.phone.domain.GlassCommandType
import com.echo.phone.domain.GlassesConnectionState
import com.echo.phone.domain.MemoryType
import com.echo.phone.domain.SpaceSceneType
import com.echo.phone.domain.TimeScene
import com.echo.phone.util.EchoLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicBoolean

class EchoApplication : Application() {
    lateinit var repository: EchoRepository
        private set
    lateinit var glassesConnection: GlassesConnection
        private set
    lateinit var recordingController: RecordingController
        private set

    val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val isRecording = AtomicBoolean(false)
    private var disconnectStop = false

    private val _recordingCompleted = MutableSharedFlow<Unit>(extraBufferCapacity = 8)
    val recordingCompleted: SharedFlow<Unit> = _recordingCompleted.asSharedFlow()
    private val _deletedMemoryId = MutableSharedFlow<String>(extraBufferCapacity = 4)
    val deletedMemoryId: SharedFlow<String> = _deletedMemoryId.asSharedFlow()
    fun notifyMemoryDeleted(memoryId: String) { _deletedMemoryId.tryEmit(memoryId) }
    private val _homeRefreshRequested = MutableSharedFlow<Unit>(extraBufferCapacity = 4)
    val homeRefreshRequested: SharedFlow<Unit> = _homeRefreshRequested.asSharedFlow()
    fun requestHomeRefresh() { _homeRefreshRequested.tryEmit(Unit) }

    // 当前正在记忆的场景；null 表示未在记忆中。
    private val _activeScene = MutableStateFlow<TimeScene?>(null)
    val activeScene: StateFlow<TimeScene?> = _activeScene.asStateFlow()

    // 记忆刚结束的场景，用于 UI 显示"xxx记忆结束"3秒后自动清除。
    private val _justCompletedScene = MutableStateFlow<TimeScene?>(null)
    val justCompletedScene: StateFlow<TimeScene?> = _justCompletedScene.asStateFlow()

    /** 下一次眼镜 START 时,若该值非空则创建 SPACE 会话(否则创建 TIME 会话)。 */
    private val _pendingSpaceSceneType = MutableStateFlow<SpaceSceneType?>(null)
    val pendingSpaceSceneType: StateFlow<SpaceSceneType?> = _pendingSpaceSceneType.asStateFlow()
    fun setPendingSpaceSceneType(type: SpaceSceneType?) { _pendingSpaceSceneType.value = type }

    /** 旁路 SPACE 录制状态(TIME 录制中用户开启 SPACE)。 */
    private val _inlineSpaceActive = MutableStateFlow(false)
    val inlineSpaceActive: StateFlow<Boolean> = _inlineSpaceActive.asStateFlow()

    override fun onCreate() {
        super.onCreate()
        EchoLog.init(this)
        repository = EchoRepository(ApiClient.service)
        glassesConnection = if (BuildConfig.USE_MOCK_GLASSES) {
            MockGlassesConnection(appScope)
        } else {
            CxrGlassesConnection(applicationContext, appScope)
        }
        recordingController = RecordingController(repository, glassesConnection, appScope, cacheDir)
        createNotificationChannel()
        EchoLog.i("Echo 手机端启动 useMock=${BuildConfig.USE_MOCK_GLASSES} api=${BuildConfig.API_BASE_URL}")
        startGlassCommandListener()
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "录制状态",
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply { description = "眼镜连接断开等录制异常通知" }
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(channel)
    }

    private fun notifyDisconnectStop() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val note = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle("眼镜连接断开")
            .setContentText("录制已自动结束，记忆已保存")
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
            .build()
        nm.notify(NOTIFY_ID_DISCONNECT, note)
    }

    private fun startGlassCommandListener() {
        EchoLog.i("已开始监听眼镜指令流(等待眼镜端 START/STOP)")
        appScope.launch {
            glassesConnection.commands.collect { command ->
                when (command.type) {
                    GlassCommandType.START -> handleStart(command)
                    GlassCommandType.STOP -> handleStop()
                }
            }
        }
        appScope.launch {
            glassesConnection.connectionState.collect { state ->
                if (state == GlassesConnectionState.DISCONNECTED && isRecording.get()) {
                    EchoLog.w("眼镜断连，自动结束录制")
                    disconnectStop = true
                    handleStop()
                }
            }
        }
    }

    private suspend fun handleStart(command: GlassCommand) {
        if (!isRecording.compareAndSet(false, true)) {
            EchoLog.w("收到眼镜START但已在录制中，忽略")
            return
        }
        val pendingSpace = _pendingSpaceSceneType.value
        val scene = command.scene ?: TimeScene.MEETING
        val partition =
            if (scene == TimeScene.QUALITY_TIME) DataPartition.QUALITY_TIME else DataPartition.WORK
        try {
            if (pendingSpace != null) {
                // 用户在 phone 上预设了 SPACE 类型,本次眼镜 START 创建 SPACE 主会话。
                EchoLog.i("收到眼镜START + pendingSpace=$pendingSpace -> 开始 SPACE 录制 sid=${command.glassSid}")
                _justCompletedScene.value = null
                val id = recordingController.startTime(
                    scene = null,
                    partition = partition,
                    title = "空间记忆",
                    glassSid = command.glassSid,
                    memoryType = MemoryType.SPACE,
                    sceneType = pendingSpace,
                )
                EchoLog.i("SPACE 录制已启动，后台 session=$id")
            } else {
                EchoLog.i("收到眼镜START scene=$scene partition=$partition sid=${command.glassSid} -> 开始 TIME 录制")
                _activeScene.value = scene
                _justCompletedScene.value = null
                val id = recordingController.startTime(scene, partition, "${scene.name} 记录", command.glassSid)
                EchoLog.i("TIME 录制已启动，后台 session=$id")
            }
        } catch (e: Exception) {
            isRecording.set(false)
            _activeScene.value = null
            EchoLog.e("开始录制失败: ${e.message}", e)
        }
    }

    /**
     * phone 首页"开启 SPACE"按钮入口:TIME 录制中调用,把后续视频分片旁路落本地。
     * 返回 SPACE 会话 id。
     */
    suspend fun startInlineSpace(sceneType: SpaceSceneType): Result<String> = runCatching {
        check(isRecording.get()) { "需在 TIME 录制中才能开启旁路 SPACE" }
        val partition = if (_activeScene.value == TimeScene.QUALITY_TIME) DataPartition.QUALITY_TIME else DataPartition.WORK
        val sessionId = recordingController.startSpace(sceneType, partition, "空间记忆")
        _inlineSpaceActive.value = true
        sessionId
    }.onFailure { EchoLog.e("开启旁路 SPACE 失败: ${it.message}", it) }

    /** phone 首页"结束 SPACE"按钮入口:关闭本地缓存,上传到 SPACE 会话,complete。 */
    suspend fun stopInlineSpace(): Result<Unit> = runCatching {
        val summary = recordingController.stopSpace()
        _inlineSpaceActive.value = false
        if (summary != null) _recordingCompleted.emit(Unit) // patch 已到达并完成时刷新
    }.onFailure {
        _inlineSpaceActive.value = false
        EchoLog.e("结束旁路 SPACE 失败: ${it.message}", it)
    }

    private suspend fun handleStop() {
        if (!isRecording.compareAndSet(true, false)) {
            EchoLog.w("收到眼镜STOP但当前未在录制，忽略")
            return
        }
        val wasDisconnect = disconnectStop
        disconnectStop = false
        val recScene = _activeScene.value
        _activeScene.value = null
        _pendingSpaceSceneType.value = null // 本次录制结束后清空 SPACE 预设
        // "xxx记忆结束" 状态不等视频/音频/IMU上传结束，收到 STOP 就立刻切换；
        // 上传进度由 RecordingController.uploadStatus 单独驱动的上传状态栏展示。
        _justCompletedScene.value = recScene
        appScope.launch {
            delay(3000)
            if (_justCompletedScene.value == recScene) _justCompletedScene.value = null
        }
        EchoLog.i("收到眼镜STOP -> 结束并上传")
        try {
            val summary = recordingController.stopAndComplete()
            EchoLog.i("记忆结束并上传完成 memoryId=${summary.memoryId} status=${summary.status}")
            _recordingCompleted.emit(Unit)
            if (wasDisconnect) notifyDisconnectStop()
        } catch (e: Exception) {
            EchoLog.e("结束/上传失败: ${e.message}", e)
        }
    }

    companion object {
        private const val CHANNEL_ID = "echo_recording"
        private const val NOTIFY_ID_DISCONNECT = 1
    }
}
