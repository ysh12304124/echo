package com.echo.phone.ui.common

import android.annotation.SuppressLint
import android.webkit.WebView
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView

/**
 * 3D 空间模型查看器：WebView + Google <model-viewer>。
 *
 * 加载后台产出的 glb 模型，支持旋转/缩放（camera-controls）。
 * 使用 model-viewer 而非 ARCore，避免额外原生依赖，便于跨设备。
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun Model3DViewer(modelUrl: String?, modifier: Modifier = Modifier) {
    AndroidView(
        modifier = modifier,
        factory = { context ->
            WebView(context).apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.allowFileAccess = true
                loadDataWithBaseURL(
                    "https://echo.local/",
                    buildHtml(modelUrl),
                    "text/html",
                    "utf-8",
                    null,
                )
            }
        },
        update = { webView ->
            webView.loadDataWithBaseURL(
                "https://echo.local/",
                buildHtml(modelUrl),
                "text/html",
                "utf-8",
                null,
            )
        },
    )
}

private fun buildHtml(modelUrl: String?): String {
    if (modelUrl.isNullOrBlank()) {
        return """
            <html><body style="margin:0;display:flex;align-items:center;justify-content:center;
            height:100vh;font-family:sans-serif;color:#888;background:#f2f2f2;">
            模型生成中…</body></html>
        """.trimIndent()
    }
    return """
        <html>
          <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <script type="module"
              src="https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js"></script>
            <style>html,body{margin:0;height:100%;background:#eceff1;}model-viewer{width:100%;height:100%;}</style>
          </head>
          <body>
            <model-viewer src="$modelUrl" camera-controls auto-rotate
              shadow-intensity="1" exposure="1"
              ar ar-modes="webxr scene-viewer"
              style="width:100%;height:100%;"></model-viewer>
          </body>
        </html>
    """.trimIndent()
}
