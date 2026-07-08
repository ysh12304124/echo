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
    private var lastToggleTime = 0L

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
                if (action != GlassKeyAction.CLICK) return@collect
                val now = System.currentTimeMillis()
                if (now - lastToggleTime < 800) return@collect
                lastToggleTime = now
                handleToggle()
            }
        }
    }

    private suspend fun handleToggle() {
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
}
