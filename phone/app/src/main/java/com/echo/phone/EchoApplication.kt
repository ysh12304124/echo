package com.echo.phone

import android.app.Application
import com.echo.phone.data.EchoRepository
import com.echo.phone.data.RecordingController
import com.echo.phone.data.api.ApiClient
import com.echo.phone.data.glasses.GlassesConnection
import com.echo.phone.data.glasses.MockGlassesConnection
import com.echo.phone.data.glasses.cxr.CxrGlassesConnection
import com.echo.phone.domain.DataPartition
import com.echo.phone.domain.GlassCommand
import com.echo.phone.domain.GlassCommandType
import com.echo.phone.domain.TimeScene
import com.echo.phone.util.EchoLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
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

    override fun onCreate() {
        super.onCreate()
        repository = EchoRepository(ApiClient.service)
        glassesConnection = if (BuildConfig.USE_MOCK_GLASSES) {
            MockGlassesConnection(appScope)
        } else {
            CxrGlassesConnection(applicationContext, appScope)
        }
        recordingController = RecordingController(repository, glassesConnection, appScope)
        EchoLog.i("Echo 手机端启动 useMock=${BuildConfig.USE_MOCK_GLASSES} api=${BuildConfig.API_BASE_URL}")
        startGlassCommandListener()
    }

    /**
     * 记忆的开始/结束完全由眼镜端主导：眼镜内选择场景后启动 START（携带场景），
     * 再次点击 STOP。手机端不再提供开始入口，仅据此驱动录制与上传。
     */
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
    }

    private suspend fun handleStart(command: GlassCommand) {
        if (!isRecording.compareAndSet(false, true)) {
            EchoLog.w("收到眼镜START但已在录制中，忽略")
            return
        }
        val scene = command.scene ?: TimeScene.MEETING
        val partition =
            if (scene == TimeScene.QUALITY_TIME) DataPartition.QUALITY_TIME else DataPartition.WORK
        EchoLog.i("收到眼镜START scene=$scene partition=$partition → 开始录制")
        try {
            val id = recordingController.startTime(scene, partition, "${scene.name} 记录")
            EchoLog.i("录制已启动，后台 session=$id")
        } catch (e: Exception) {
            isRecording.set(false)
            EchoLog.e("开始录制失败: ${e.message}", e)
        }
    }

    private suspend fun handleStop() {
        if (!isRecording.compareAndSet(true, false)) {
            EchoLog.w("收到眼镜STOP但当前未在录制，忽略")
            return
        }
        EchoLog.i("收到眼镜STOP → 结束并上传")
        try {
            val summary = recordingController.stopAndComplete()
            EchoLog.i("记忆结束并上传完成 memoryId=${summary.memoryId} status=${summary.status}")
        } catch (e: Exception) {
            EchoLog.e("结束/上传失败: ${e.message}", e)
        }
    }
}
