package com.echo.phone

import android.app.Application
import android.util.Log
import com.echo.phone.data.EchoRepository
import com.echo.phone.data.RecordingController
import com.echo.phone.data.api.ApiClient
import com.echo.phone.data.glasses.GlassesConnection
import com.echo.phone.data.glasses.MockGlassesConnection
import com.echo.phone.data.glasses.cxr.CxrGlassesConnection
import com.echo.phone.domain.DataPartition
import com.echo.phone.domain.GlassKeyAction
import com.echo.phone.domain.TimeScene
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
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
    private var lastClickTime = 0L

    override fun onCreate() {
        super.onCreate()
        repository = EchoRepository(ApiClient.service)
        glassesConnection = if (BuildConfig.USE_MOCK_GLASSES) {
            MockGlassesConnection(appScope)
        } else {
            CxrGlassesConnection(applicationContext, appScope)
        }
        recordingController = RecordingController(repository, glassesConnection, appScope)
        startGlassKeyListener()
    }

    private fun startGlassKeyListener() {
        appScope.launch {
            glassesConnection.keyEvents.collect { action ->
                Log.d("EchoApp", "GlassKey: $action recording=${isRecording.get()}")
                when (action) {
                    GlassKeyAction.CLICK -> handleClick()
                    GlassKeyAction.DOUBLE_CLICK -> handleDoubleClick()
                    GlassKeyAction.LONG_PRESS -> handleLongPress()
                    GlassKeyAction.SWIPE_FORWARD,
                    GlassKeyAction.SWIPE_BACK,
                    GlassKeyAction.OTHER -> { /* skip */ }
                }
            }
        }
    }

    private suspend fun handleClick() {
        val now = System.currentTimeMillis()
        if (now - lastClickTime < 600) return  // 600ms 防抖
        lastClickTime = now

        if (isRecording.get()) {
            withContext(Dispatchers.IO) {
                try {
                    recordingController.stopAndComplete()
                    isRecording.set(false)
                } catch (e: Exception) {
                    Log.e("EchoApp", "stop failed", e)
                }
            }
        } else {
            withContext(Dispatchers.IO) {
                try {
                    recordingController.startTime(
                        TimeScene.MEETING, DataPartition.WORK, "会议记录"
                    )
                    isRecording.set(true)
                } catch (e: Exception) {
                    Log.e("EchoApp", "start failed", e)
                }
            }
        }
    }

    private suspend fun handleDoubleClick() {
        if (!isRecording.get()) return
        withContext(Dispatchers.IO) {
            try {
                recordingController.pause()
            } catch (e: Exception) {
                Log.e("EchoApp", "pause failed", e)
            }
        }
    }

    private suspend fun handleLongPress() {
        if (!isRecording.get()) return
        withContext(Dispatchers.IO) {
            try {
                recordingController.markKeyMoment()
            } catch (e: Exception) {
                Log.e("EchoApp", "markKeyMoment failed", e)
            }
        }
    }
}
