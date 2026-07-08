package com.echo.phone

import android.app.Application
import com.echo.phone.data.EchoRepository
import com.echo.phone.data.RecordingController
import com.echo.phone.data.api.ApiClient
import com.echo.phone.data.glasses.GlassesConnection
import com.echo.phone.data.glasses.MockGlassesConnection
import com.echo.phone.data.glasses.cxr.CxrGlassesConnection
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

class EchoApplication : Application() {
    lateinit var repository: EchoRepository
        private set
    lateinit var glassesConnection: GlassesConnection
        private set
    lateinit var recordingController: RecordingController
        private set

    val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onCreate() {
        super.onCreate()
        repository = EchoRepository(ApiClient.service)
        // USE_MOCK_GLASSES=true：无真机离线开发，用 Mock 周期产生合成帧/音频。
        // false：接真实 Rokid CXR-L 眼镜（鉴权/会话/音频/拍照/按键由眼镜经 CXR-L 送达）。
        glassesConnection = if (BuildConfig.USE_MOCK_GLASSES) {
            MockGlassesConnection(appScope)
        } else {
            CxrGlassesConnection(applicationContext, appScope)
        }
        recordingController = RecordingController(repository, glassesConnection, appScope)
    }
}
