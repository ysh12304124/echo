package com.echo.phone

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.material3.Surface
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.echo.phone.data.glasses.cxr.CxrGlassesConnection
import com.echo.phone.ui.EchoApp
import com.echo.phone.ui.theme.EchoTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        // 真机模式下，CXR-L 鉴权需 Activity 与 onActivityResult 配合。
        (application as EchoApplication).glassesConnection.let { conn ->
            if (conn is CxrGlassesConnection) conn.attachActivity(this)
        }
        // 场景记忆改由手机麦克风录音，需要运行时录音权限。
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.RECORD_AUDIO), REQUEST_CODE_RECORD_AUDIO)
        }
        setContent {
            EchoTheme(darkTheme = false) {
                Surface {
                    EchoApp()
                }
            }
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        val conn = (application as EchoApplication).glassesConnection
        if (conn is CxrGlassesConnection && requestCode == CxrGlassesConnection.REQUEST_CODE_AUTH) {
            conn.onAuthResult(resultCode, data)
        }
    }

    private companion object {
        const val REQUEST_CODE_RECORD_AUDIO = 0xEC02
    }
}
