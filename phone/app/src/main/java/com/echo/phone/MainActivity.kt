package com.echo.phone

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.material3.Surface
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
        setContent {
            EchoTheme {
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
}
