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
import com.echo.phone.domain.SpaceType
import com.echo.phone.domain.TimeScene
import com.echo.phone.util.EchoLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
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

    // Space recording: phone needs to pick scene type before starting
    private val _pendingSpaceStart = MutableSharedFlow<Pair<GlassCommand, (SpaceType) -> Unit>>(extraBufferCapacity = 1)
    val pendingSpaceStart: SharedFlow<Pair<GlassCommand, (SpaceType) -> Unit>> = _pendingSpaceStart.asSharedFlow()

    private val _currentRecordingType = MutableStateFlow<RecordingType>(RecordingType.NONE)
    val currentRecordingType: StateFlow<RecordingType> = _currentRecordingType.asStateFlow()

    enum class RecordingType { NONE, TIME, SPACE }

    override fun onCreate() {
        super.onCreate()
        repository = EchoRepository(ApiClient.service)
        glassesConnection = if (BuildConfig.USE_MOCK_GLASSES) {
            MockGlassesConnection(appScope)
        } else {
            CxrGlassesConnection(applicationContext, appScope)
        }
        recordingController = RecordingController(repository, glassesConnection, appScope)
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
                    GlassCommandType.START -> {
                        if (command.scene == TimeScene.SPACE) {
                            // Space needs user to pick scene type first
                            _pendingSpaceStart.emit(command to { spaceType -> confirmSpaceStart(command, spaceType) })
                        } else {
                            handleStart(command)
                        }
                    }
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

    private fun confirmSpaceStart(command: GlassCommand, spaceType: SpaceType) {
        appScope.launch {
            handleStart(command, spaceType)
        }
    }

    private suspend fun handleStart(command: GlassCommand, spaceType: SpaceType? = null) {
        if (!isRecording.compareAndSet(false, true)) {
            EchoLog.w("收到眼镜START但已在录制中，忽略")
            return
        }
        val scene = command.scene ?: TimeScene.MEETING
        val partition =
            if (scene == TimeScene.QUALITY_TIME) DataPartition.QUALITY_TIME else DataPartition.WORK
        EchoLog.i("收到眼镜START scene=$scene partition=$partition -> 开始录制")
        try {
            if (scene == TimeScene.SPACE) {
                val st = spaceType ?: SpaceType.LARGE_SCENE
                _currentRecordingType.value = RecordingType.SPACE
                val id = recordingController.startSpace(st, partition, "${st.label} 空间记忆")
                EchoLog.i("空间录制已启动，后台 session=$id")
            } else {
                _currentRecordingType.value = RecordingType.TIME
                val id = recordingController.startTime(scene, partition, "${scene.name} 记录")
                EchoLog.i("录制已启动，后台 session=$id")
            }
        } catch (e: Exception) {
            isRecording.set(false)
            _currentRecordingType.value = RecordingType.NONE
            EchoLog.e("开始录制失败: ${e.message}", e)
        }
    }

    private suspend fun handleStop() {
        if (!isRecording.compareAndSet(true, false)) {
            EchoLog.w("收到眼镜STOP但当前未在录制，忽略")
            return
        }
        val wasDisconnect = disconnectStop
        disconnectStop = false
        val recType = _currentRecordingType.value
        _currentRecordingType.value = RecordingType.NONE
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
