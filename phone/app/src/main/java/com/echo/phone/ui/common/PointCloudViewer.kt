package com.echo.phone.ui.common

import android.annotation.SuppressLint
import android.app.Activity
import android.content.pm.ActivityInfo
import android.view.MotionEvent
import android.webkit.ConsoleMessage
import android.webkit.WebChromeClient
import android.webkit.WebView
import androidx.compose.foundation.background

import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupProperties
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.echo.phone.BuildConfig
import com.echo.phone.domain.CameraPose
import com.echo.phone.domain.OrbitCircle
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.roundToInt
import kotlin.math.sqrt

private val BASE_URL = BuildConfig.API_BASE_URL.removeSuffix("/api/v1/").removeSuffix("/")

@SuppressLint("SetJavaScriptEnabled", "ClickableViewAccessibility")
@Composable
fun PointCloudViewer(
    pointCloudUrl: String?,
    poses: List<CameraPose> = emptyList(),
    orbitCircle: OrbitCircle? = null,
    baseSpeed: Float = 1f,
    sceneType: String = "large",
    modifier: Modifier = Modifier,
) {
    val path = pointCloudUrl?.removePrefix(BASE_URL) ?: ""
    val plyJs = if (path.isNotBlank()) "\"" + path + "\"" else "null"
    val posesJson = if (poses.isNotEmpty()) {
        "[" + poses.joinToString(",") { p ->
            "{\"px\":" + p.position[0] + ",\"py\":" + p.position[1] + ",\"pz\":" + p.position[2] +
            ",\"fx\":" + p.forward[0] + ",\"fy\":" + p.forward[1] + ",\"fz\":" + p.forward[2] + "}"
        } + "]"
    } else "null"

    val orbitJson = orbitCircle?.let {
        "{\"cx\":" + it.center[0] + ",\"cy\":" + it.center[1] + ",\"cz\":" + it.center[2] +
        ",\"r\":" + it.radius + ",\"nx\":" + it.normal[0] + ",\"ny\":" + it.normal[1] + ",\"nz\":" + it.normal[2] + "}"
    } ?: "null"

    val html = buildViewerHtml(plyJs, posesJson, orbitJson)

    val webViewRef = remember { mutableMapOf< String, WebView>() }
    var pageLoaded by remember { mutableStateOf(false) }
    var isFullscreen by remember { mutableStateOf(false) }
    var currentMode by remember { mutableStateOf(if (sceneType == "object") "orbit" else "path") }
    var speedMult by remember { mutableStateOf(1f) }
    var popupExpanded by remember { mutableStateOf(true) }
    val context = LocalContext.current
    val activity = context as Activity

    // Orientation control
    activity.requestedOrientation = if (isFullscreen) {
        ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
    } else {
        ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
    }

    if (isFullscreen) {
        activity.window?.decorView?.systemUiVisibility = (
            android.view.View.SYSTEM_UI_FLAG_FULLSCREEN
                or android.view.View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                or android.view.View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                or android.view.View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                or android.view.View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                or android.view.View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
        )
    } else {
        activity.window?.decorView?.systemUiVisibility = android.view.View.SYSTEM_UI_FLAG_VISIBLE
    }

    fun makeWebView(ctx: android.content.Context): WebView {
        return WebView(ctx).apply {
            setLayerType(android.view.View.LAYER_TYPE_HARDWARE, null)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = true
            setWebChromeClient(object : WebChromeClient() {
                override fun onConsoleMessage(msg: ConsoleMessage): Boolean {
                    val sdf = SimpleDateFormat("HH:mm:ss.SSS", Locale.US)
                    val line = "[" + msg.messageLevel() + "] " + msg.message() + " (" + msg.sourceId() + ":" + msg.lineNumber() + ")"
                    android.util.Log.w("ECHO_WEB", line)
                    try { File(ctx.filesDir, "webview.log").appendText(sdf.format(Date()) + " " + line + "\n") } catch (_: Exception) {}
                    return true
                }
            })
        }
    }

    val viewerWebView = remember(html) {
        makeWebView(context).apply {
            webViewClient = object : android.webkit.WebViewClient() {
                override fun onPageFinished(view: WebView?, url: String?) {
                    pageLoaded = true
                }
            }
            loadDataWithBaseURL(BASE_URL + "/", html, "text/html", "utf-8", null)
            setOnTouchListener { _, event ->
                when (event.action) {
                    MotionEvent.ACTION_DOWN -> parent?.requestDisallowInterceptTouchEvent(true)
                    MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> parent?.requestDisallowInterceptTouchEvent(false)
                }
                false
            }
            webViewRef["wv"] = this
        }
    }
    var fullscreenWebView by remember { mutableStateOf<WebView?>(null) }
    var savedCameraState by remember { mutableStateOf<String?>(null) }
    fun closeFullscreen() {
        fullscreenWebView?.apply {
            evaluateJavascript("disposeViewer()", null)
            stopLoading()
            destroy()
        }
        fullscreenWebView = null
        webViewRef["wv"] = viewerWebView
        isFullscreen = false
    }

    LaunchedEffect(isFullscreen) {
        if (isFullscreen) {
            webViewRef["wv"]?.evaluateJavascript("exportView()") { result ->
                savedCameraState = result.removeSurrounding("\"").replace("\\\"", "\"")
            }
        }
    }
    DisposableEffect(viewerWebView) {
        onDispose {
            fullscreenWebView?.destroy()
            viewerWebView.evaluateJavascript("disposeViewer()", null)
            viewerWebView.stopLoading()
            viewerWebView.destroy()
            webViewRef.remove("wv")
        }
    }

    // State for controls
    var upHeld by remember { mutableStateOf(false) }
    var downHeld by remember { mutableStateOf(false) }
    var jx by remember { mutableStateOf(0f) }
    var jy by remember { mutableStateOf(0f) }
    var jActive by remember { mutableStateOf(false) }
    var jVisible by remember { mutableStateOf(false) }
    var jBaseX by remember { mutableStateOf(0f) }
    var jBaseY by remember { mutableStateOf(0f) }
    var orbitPrevX by remember { mutableStateOf(0f) }
    var orbitPrevY by remember { mutableStateOf(0f) }
    var orbiting by remember { mutableStateOf(false) }
    var orbitSwipeActive by remember { mutableStateOf(false) }

    // Sync the pose-derived orbit circle and mode to JS after the page loads.
    LaunchedEffect(currentMode, pageLoaded, orbitCircle) {
        if (pageLoaded) {
            if (orbitCircle != null) {
                val orbJs = "{\"cx\":${orbitCircle.center[0]},\"cy\":${orbitCircle.center[1]},\"cz\":${orbitCircle.center[2]},\"r\":${orbitCircle.radius},\"nx\":${orbitCircle.normal[0]},\"ny\":${orbitCircle.normal[1]},\"nz\":${orbitCircle.normal[2]}}"
                webViewRef["wv"]?.evaluateJavascript("setOrbitData($orbJs)", null)
            }
            webViewRef["wv"]?.evaluateJavascript("setMode('$currentMode')", null)
        }
    }
    LaunchedEffect(isFullscreen, pageLoaded) {
        if (pageLoaded && isFullscreen && currentMode == "orbit") {
            webViewRef["wv"]?.evaluateJavascript("setMode('orbit')", null)
        }
    }
    LaunchedEffect(speedMult, pageLoaded, baseSpeed) {
        if (pageLoaded && poses.isNotEmpty()) {
            webViewRef["wv"]?.evaluateJavascript("setSpeed(${baseSpeed * speedMult})", null)
        }
    }

    // Continuous movement loop for path mode
    if (isFullscreen && currentMode == "path") {
        LaunchedEffect(Unit) {
            while (true) {
                if (upHeld) webViewRef["wv"]?.evaluateJavascript("movePath(1)", null)
                else if (downHeld) webViewRef["wv"]?.evaluateJavascript("movePath(-1)", null)
                else webViewRef["wv"]?.evaluateJavascript("stopPath()", null)
                kotlinx.coroutines.delay(16)
            }
        }
    }

    if (isFullscreen) {
        Dialog(
            onDismissRequest = ::closeFullscreen,
            properties = DialogProperties(
                usePlatformDefaultWidth = false,
                dismissOnBackPress = true,
                dismissOnClickOutside = false
            )
        ) {
            val dialogWindow = (LocalView.current.parent as? android.app.Dialog)?.window
            LaunchedEffect(dialogWindow) {
                dialogWindow?.apply {
                    setFlags(
                        android.view.WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                        android.view.WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                    )
                    decorView?.systemUiVisibility = (
                        android.view.View.SYSTEM_UI_FLAG_FULLSCREEN
                            or android.view.View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                            or android.view.View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                            or android.view.View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            or android.view.View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            or android.view.View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                    )
                }
            }
            Box(modifier = Modifier.fillMaxSize().background(Color.Black)) {

                // WebView
                AndroidView(
                    modifier = Modifier.fillMaxSize(),
                    factory = { ctx ->
                        makeWebView(ctx).apply {
                            webViewClient = object : android.webkit.WebViewClient() {
                                override fun onPageFinished(view: WebView?, url: String?) {
                                    val state = savedCameraState
                                    val restore = state?.replace("\\", "\\\\")?.replace("'", "\\'")
                                    if (restore != null) {
                                        evaluateJavascript("setMode('$currentMode');restoreView('$restore')", null)
                                    } else {
                                        evaluateJavascript("setMode('$currentMode')", null)
                                    }
                                }
                            }
                            loadDataWithBaseURL(BASE_URL + "/", html, "text/html", "utf-8", null)
                            fullscreenWebView = this
                            webViewRef["wv"] = this
                        }
                    },
                )
                // ---- Path mode: ▲▼ buttons ----
                if (currentMode == "path") {
                    Column(
                        modifier = Modifier.align(Alignment.CenterStart).padding(start = 24.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Box(
                            Modifier.size(56.dp).clip(CircleShape)
                                .background(Color.White.copy(alpha = if (upHeld) 0.25f else 0.1f))
                                .pointerInput(Unit) {
                                    awaitPointerEventScope {
                                        var wasPressed = false
                                        while (true) {
                                            val pressed = awaitPointerEvent().changes.any { it.pressed }
                                            if (pressed && !wasPressed) {
                                                // 短点击可能在 16ms 持续循环采样前释放，按下瞬间补一次离散移动。
                                                webViewRef["wv"]?.evaluateJavascript("movePath(1)", null)
                                            }
                                            upHeld = pressed
                                            wasPressed = pressed
                                        }
                                    }
                                },
                            contentAlignment = Alignment.Center,
                        ) {
                            Text("▲", color = Color.White.copy(alpha = if (upHeld) 1f else 0.5f), fontSize = 20.sp)
                        }
                        Box(
                            Modifier.size(56.dp).clip(CircleShape)
                                .background(Color.White.copy(alpha = if (downHeld) 0.25f else 0.1f))
                                .pointerInput(Unit) {
                                    awaitPointerEventScope {
                                        var wasPressed = false
                                        while (true) {
                                            val pressed = awaitPointerEvent().changes.any { it.pressed }
                                            if (pressed && !wasPressed) {
                                                webViewRef["wv"]?.evaluateJavascript("movePath(-1)", null)
                                            }
                                            downHeld = pressed
                                            wasPressed = pressed
                                        }
                                    }
                                },
                            contentAlignment = Alignment.Center,
                        ) {
                            Text("▼", color = Color.White.copy(alpha = if (downHeld) 1f else 0.5f), fontSize = 20.sp)
                        }
                    }
                }

                // ---- Right-half: orbit/rotate ----
                if (currentMode == "path") {
                    // Right half drag for free rotation (path mode)
                    Box(
                        modifier = Modifier.fillMaxHeight().fillMaxWidth(0.5f).align(Alignment.CenterEnd)
                            .pointerInput(Unit) {
                                detectDragGestures(
                                    onDragStart = { offset ->
                                        orbiting = true
                                        orbitPrevX = offset.x; orbitPrevY = offset.y
                                    },
                                    onDragEnd = { orbiting = false },
                                    onDragCancel = { orbiting = false },
                                    onDrag = { change, dragAmount ->
                                        change.consume()
                                        webViewRef["wv"]?.evaluateJavascript(
                                            "orbitView(" + dragAmount.x + "," + dragAmount.y + ")", null
                                        )
                                    },
                                )
                            }
                    )
                } else if (currentMode == "orbit") {
                    // Left half: drag for sphere orbit (horizontal=longitude, vertical=latitude)
                    Box(
                        modifier = Modifier.fillMaxHeight().fillMaxWidth(0.5f).align(Alignment.CenterStart)
                            .pointerInput(Unit) {
                                detectDragGestures(
                                    onDragStart = { orbitSwipeActive = true },
                                    onDragEnd = { orbitSwipeActive = false },
                                    onDragCancel = { orbitSwipeActive = false },
                                    onDrag = { change, dragAmount ->
                                        change.consume()
                                        webViewRef["wv"]?.evaluateJavascript(
                                            "swipeOrbit(" + dragAmount.x + "," + dragAmount.y + ")", null
                                        )
                                    },
                                )
                            }
                    )
                    // Right half: micro-adjust view (±30° clamped in JS)
                    Box(
                        modifier = Modifier.fillMaxHeight().fillMaxWidth(0.5f).align(Alignment.CenterEnd)
                            .pointerInput(Unit) {
                                detectDragGestures(
                                    onDragStart = { orbitPrevX = 0f; orbitPrevY = 0f },
                                    onDrag = { change, dragAmount ->
                                        change.consume()
                                        webViewRef["wv"]?.evaluateJavascript(
                                            "orbitView(" + dragAmount.x + "," + dragAmount.y + ")", null
                                        )
                                    },
                                )
                            }
                    )
                } else {
                    // Free roam mode: existing controls
                    // Left half joystick
                    val outerR = 70.dp
                    val innerR = 28.dp
                    Box(
                        modifier = Modifier.fillMaxHeight().fillMaxWidth(0.5f).align(Alignment.CenterStart)
                            .pointerInput(Unit) {
                                detectDragGestures(
                                    onDragStart = { offset ->
                                        jVisible = true; jActive = true
                                        jBaseX = offset.x; jBaseY = offset.y; jx = 0f; jy = 0f
                                    },
                                    onDragEnd = { jVisible = false; jActive = false; jx = 0f; jy = 0f },
                                    onDragCancel = { jVisible = false; jActive = false; jx = 0f; jy = 0f },
                                    onDrag = { change, dragAmount ->
                                        change.consume()
                                        val maxR = outerR.toPx() - innerR.toPx()
                                        val nx = (jx * maxR + dragAmount.x).coerceIn(-maxR, maxR)
                                        val ny = (jy * maxR + dragAmount.y).coerceIn(-maxR, maxR)
                                        val dist = sqrt(nx * nx + ny * ny)
                                        if (dist > maxR) { jx = nx / dist; jy = ny / dist }
                                        else { jx = nx / maxR; jy = ny / maxR }
                                    },
                                )
                            }
                    ) {
                        if (jVisible) {
                            Box(
                                modifier = Modifier
                                    .offset { IntOffset((jBaseX - outerR.toPx()).roundToInt(), (jBaseY - outerR.toPx()).roundToInt()) }
                                    .size(outerR * 2)
                            ) {
                                Box(
                                    Modifier.size(outerR * 2).clip(CircleShape)
                                        .background(Color.White.copy(alpha = 0.12f)),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Box(
                                        Modifier.size(innerR * 2)
                                            .offset {
                                                IntOffset(
                                                    (jx * (outerR.toPx() - innerR.toPx())).roundToInt(),
                                                    (jy * (outerR.toPx() - innerR.toPx())).roundToInt(),
                                                )
                                            }
                                            .clip(CircleShape).background(Color.White.copy(alpha = 0.4f))
                                    )
                                }
                            }
                        }
                    }

                    // Right half orbit
                    Box(
                        modifier = Modifier.fillMaxHeight().fillMaxWidth(0.5f).align(Alignment.CenterEnd)
                            .pointerInput(Unit) {
                                detectDragGestures(
                                    onDragStart = { offset ->
                                        orbiting = true
                                        orbitPrevX = offset.x; orbitPrevY = offset.y
                                    },
                                    onDragEnd = { orbiting = false },
                                    onDragCancel = { orbiting = false },
                                    onDrag = { change, dragAmount ->
                                        change.consume()
                                        webViewRef["wv"]?.evaluateJavascript(
                                            "orbitView(" + dragAmount.x + "," + dragAmount.y + ")", null
                                        )
                                    },
                                )
                            }
                    )

                    // ▲▼ for free roam
                    Column(
                        modifier = Modifier.align(Alignment.CenterEnd).padding(end = 24.dp, bottom = 80.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Box(
                            Modifier.size(56.dp).clip(CircleShape)
                                .background(Color.White.copy(alpha = if (upHeld) 0.25f else 0.1f))
                                .pointerInput(Unit) {
                                    awaitPointerEventScope {
                                        while (true) { upHeld = awaitPointerEvent().changes.any { it.pressed } }
                                    }
                                },
                            contentAlignment = Alignment.Center,
                        ) {
                            Text("▲", color = Color.White.copy(alpha = if (upHeld) 1f else 0.5f), fontSize = 20.sp)
                        }
                        Box(
                            Modifier.size(56.dp).clip(CircleShape)
                                .background(Color.White.copy(alpha = if (downHeld) 0.25f else 0.1f))
                                .pointerInput(Unit) {
                                    awaitPointerEventScope {
                                        while (true) { downHeld = awaitPointerEvent().changes.any { it.pressed } }
                                    }
                                },
                            contentAlignment = Alignment.Center,
                        ) {
                            Text("▼", color = Color.White.copy(alpha = if (downHeld) 1f else 0.5f), fontSize = 20.sp)
                        }
                    }
                }

                // Free roam continuous movement
                if (isFullscreen && currentMode == "free") {
                    LaunchedEffect(Unit) {
                        while (true) {
                            if (jActive || upHeld || downHeld) {
                                val dy = if (upHeld) 1f else if (downHeld) -1f else 0f
                                webViewRef["wv"]?.evaluateJavascript(
                                    "moveCam(" + jx * 0.3f + "," + dy * 0.3f + "," + -jy * 0.3f + ")", null
                                )
                            }
                            kotlinx.coroutines.delay(16)
                        }
                    }
                }

                // ---- Bottom-right buttons ----
                Column(
                    modifier = Modifier.align(Alignment.BottomEnd).padding(12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Box(
                        Modifier.size(40.dp).clip(CircleShape)
                            .background(Color.Black.copy(alpha = 0.5f))
                            .pointerInput(Unit) { detectTapGestures { webViewRef["wv"]?.evaluateJavascript("resetView()", null) } },
                        contentAlignment = Alignment.Center,
                    ) { Text("↺", color = Color(0xFFCCCCCC), fontSize = 16.sp) }
                    Box(
                        Modifier.size(40.dp).clip(CircleShape)
                            .background(Color.Black.copy(alpha = 0.5f))
                            .pointerInput(Unit) { detectTapGestures { closeFullscreen() } },
                        contentAlignment = Alignment.Center,
                    ) { Text("⬒", color = Color(0xFFCCCCCC), fontSize = 14.sp) }
                }

            }

    // Popup top bar (renders above WebView in its own window)
    Popup(
        alignment = Alignment.TopCenter,
        properties = PopupProperties(focusable = false),
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(top = 48.dp),
        ) {
            // Toggle button - always visible
            Box(
                modifier = Modifier.size(32.dp, 16.dp).clip(RoundedCornerShape(8.dp))
                    .background(Color.Black.copy(alpha = 0.6f))
                    .pointerInput(Unit) { detectTapGestures { popupExpanded = !popupExpanded } },
                contentAlignment = Alignment.Center,
            ) {
                Text(if (popupExpanded) "▲" else "▼", color = Color.White.copy(alpha = 0.7f), fontSize = 8.sp)
            }
            // Expandable controls
            if (popupExpanded) {
                Column(
                    modifier = Modifier
                        .background(Color.Black.copy(alpha = 0.75f), RoundedCornerShape(12.dp))
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                ) {
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        val tabLabel = if (sceneType == "object") "物体环绕" else "路径浏览"
                        val defaultMode = if (sceneType == "object") "orbit" else "path"
                        Box(
                            modifier = Modifier.clip(RoundedCornerShape(8.dp))
                                .background(if (currentMode != "free") Color.White.copy(alpha = 0.25f) else Color.White.copy(alpha = 0.08f))
                                .pointerInput(Unit) { detectTapGestures { currentMode = defaultMode } }
                                .padding(horizontal = 14.dp, vertical = 6.dp),
                        ) {
                            Text(tabLabel, color = Color.White, fontSize = 13.sp)
                        }
                        Box(
                            modifier = Modifier.clip(RoundedCornerShape(8.dp))
                                .background(if (currentMode == "free") Color.White.copy(alpha = 0.25f) else Color.White.copy(alpha = 0.08f))
                                .pointerInput(Unit) { detectTapGestures { currentMode = "free" } }
                                .padding(horizontal = 14.dp, vertical = 6.dp),
                        ) {
                            Text("自由漫游", color = Color.White, fontSize = 13.sp)
                        }
                    }
                    Spacer(modifier = Modifier.size(4.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("速度", color = Color.White.copy(alpha = 0.6f), fontSize = 11.sp)
                        Slider(
                            value = speedMult,
                            onValueChange = { speedMult = it },
                            valueRange = 0.5f..3f,
                            modifier = Modifier.width(140.dp).height(28.dp),
                            colors = SliderDefaults.colors(
                                thumbColor = Color.White,
                                activeTrackColor = Color.White.copy(alpha = 0.7f),
                                inactiveTrackColor = Color.White.copy(alpha = 0.2f),
                            ),
                        )
                        Text("%.1fx".format(speedMult), color = Color.White.copy(alpha = 0.6f), fontSize = 11.sp)
                    }
                }
            }
        }
        }
    }
    }

    // Normal mode (card view)
    if (!isFullscreen) Box(modifier = modifier) {
        AndroidView(
            modifier = Modifier.matchParentSize(),
            factory = { viewerWebView },
        )
        Row(
            modifier = Modifier.align(Alignment.BottomEnd).padding(12.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Box(
                Modifier.size(40.dp).clip(CircleShape)
                    .background(Color.Black.copy(alpha = 0.5f))
                    .pointerInput(Unit) { detectTapGestures { webViewRef["wv"]?.evaluateJavascript("resetView()", null) } },
                contentAlignment = Alignment.Center,
            ) { Text("↺", color = Color(0xFFCCCCCC), fontSize = 16.sp) }
            Box(
                Modifier.size(40.dp).clip(CircleShape)
                    .background(Color.Black.copy(alpha = 0.5f))
                    .pointerInput(Unit) { detectTapGestures { isFullscreen = true } },
                contentAlignment = Alignment.Center,
            ) { Text("⛶", color = Color(0xFFCCCCCC), fontSize = 14.sp) }
        }
    }
}

private fun buildViewerHtml(plyJs: String, posesJson: String, orbitJson: String): String {
    return """<!DOCTYPE html><html><body style='margin:0;background:#000;overflow:hidden;'>
<canvas id='c' style='width:100%;height:100%;touch-action:none;'></canvas>
<div id='loading' style='position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:10;pointer-events:none;text-align:center;'>
<div id='loadingText' style='color:#aaa;font:14px sans-serif;margin-bottom:10px;'>Loading GS...</div>
<div id='loadingBarWrap' style='width:200px;height:4px;background:rgba(255,255,255,0.1);border-radius:2px;overflow:hidden;margin:0 auto;'>
<div id='loadingBar' style='width:0%;height:100%;background:rgba(255,255,255,0.5);border-radius:2px;transition:width 0.3s;'></div>
</div></div>
<script>
var W=window.innerWidth,H=window.innerHeight,D=devicePixelRatio||2;
var PLY=$plyJs;
var SOURCE_POSES=$posesJson;
// COLMAP recordings use Y-down/Z-forward while PlayCanvas is Y-up/Z-back.
// Apply (x,y,z)->(x,-y,-z) to poses and the model together.
var POSES=SOURCE_POSES&&SOURCE_POSES.map(function(p){return {px:p.px,py:-p.py,pz:-p.pz,fx:p.fx,fy:-p.fy,fz:-p.fz};});
var ORBIT=$orbitJson;
if(ORBIT){ORBIT={cx:ORBIT.cx,cy:-ORBIT.cy,cz:-ORBIT.cz,r:ORBIT.r,nx:ORBIT.nx,ny:-ORBIT.ny,nz:-ORBIT.nz};}
</script>
<script src='$BASE_URL/api/v1/media/threejs/playcanvas.min.js'></script>
<script>
(function(){
var canvas=document.getElementById('c');
canvas.width=W*Math.min(D,2);canvas.height=H*Math.min(D,2);
var loadingEl=document.getElementById('loading');
var loadingText=document.getElementById('loadingText');
var loadingBar=document.getElementById('loadingBar');
var loadingBarWrap=document.getElementById('loadingBarWrap');

// Camera state
var theta=0,phi=Math.PI/3,radius=3;
var tx=0,ty=0,tz=0;
var initTheta=0,initPhi=Math.PI/3,initRadius=3,initTx=0,initTy=0,initTz=0;
var camEnt=null,app=null;

// Orbit always targets the GS bounding-box center. Keep it separate from the
// free/path camera state so a gesture can never move the orbit target.
var orbitCenterX=0,orbitCenterY=0,orbitCenterZ=0;
var sceneRadius=1;
var pathBackOffset=0.4,pathUpOffset=0.15,pathDownTilt=0.12;

// Path following state
var pathMode='free';  // 'path', 'orbit', 'free'
var pathDistance=0;
var pathSpeed=1.0; // model-coordinate units per second
var lastPathTime=0;
var pathSegmentLengths=null,pathTotalLength=0;

// Orbit state
var orbitUserDH=0, orbitUserDV=0;
var ORBIT_MAX_ADJUST=30*Math.PI/180; // ±30 degrees

function camPos(){
  var st=Math.sin(theta),ct=Math.cos(theta),sp=Math.sin(phi),cp=Math.cos(phi);
  var cx=pathMode==='orbit'?orbitCenterX:tx;
  var cy=pathMode==='orbit'?orbitCenterY:ty;
  var cz=pathMode==='orbit'?orbitCenterZ:tz;
  return{x:cx+radius*sp*ct,y:cy+radius*cp,z:cz+radius*sp*st};
}

function setCameraDirection(fx,fy,fz){
  var fl=Math.sqrt(fx*fx+fy*fy+fz*fz)||1;
  fx/=fl;fy/=fl;fz/=fl;
  // Camera looks along local -Z. Build an orthonormal basis from the desired
  // world-space forward vector and world up, with a fallback near the poles.
  var rx=-fz,ry=0,rz=fx; var rl=Math.sqrt(rx*rx+rz*rz);
  if(rl>0.001){rx/=rl;rz/=rl;}else{rx=1;ry=0;rz=0;}
  var ux=ry*fz-rz*fy,uy=rz*fx-rx*fz,uz=rx*fy-ry*fx;
  var m=new pc.Mat4();
  m.data.set([rx,ry,rz,0, ux,uy,uz,0, -fx,-fy,-fz,0, 0,0,0,1]);
  var q=new pc.Quat();q.setFromMat4(m);
  camEnt.setRotation(q);
}

function applyCam(){
  if(!camEnt)return;
  if(pathMode==='path'){
    camEnt.setPosition(tx,ty,tz);
    var fx=Math.sin(phi)*Math.cos(theta);
    var fy=Math.cos(phi);
    var fz=Math.sin(phi)*Math.sin(theta);
    setCameraDirection(fx,fy,fz);
  }else if(pathMode==='orbit'){
    var p=camPos();camEnt.setPosition(p.x,p.y,p.z);
    // Orbit gestures change only the spherical camera position. Recompute the
    // view direction from that position to the fixed center on every update.
    setCameraDirection(orbitCenterX-p.x,orbitCenterY-p.y,orbitCenterZ-p.z);
  }else{
    var p=camPos();camEnt.setPosition(p.x,p.y,p.z);
    var st=Math.sin(theta),ct=Math.cos(theta),sp=Math.sin(phi),cp=Math.cos(phi);
    var rx=-st,ry=0,rz=ct;
    var ux=cp*ct,uy=-sp,uz=cp*st;
    var zx=sp*ct,zy=cp,zz=sp*st;
    var m=new pc.Mat4();
    m.data.set([rx,ry,rz,0, ux,uy,uz,0, zx,zy,zz,0, 0,0,0,1]);
    var q=new pc.Quat();q.setFromMat4(m);
    camEnt.setRotation(q);
  }
}

function shortestAngleDelta(from,to){
  var full=Math.PI*2;
  return ((to-from+Math.PI)%full+full)%full-Math.PI;
}
function prepareClosedPath(){
  if(!POSES||POSES.length<2)return;
  pathSegmentLengths=[];pathTotalLength=0;
  for(var i=0;i<POSES.length;i++){
    var a=POSES[i],b=POSES[(i+1)%POSES.length];
    var dx=b.px-a.px,dy=b.py-a.py,dz=b.pz-a.pz;
    var len=Math.sqrt(dx*dx+dy*dy+dz*dz);
    pathSegmentLengths.push(len);pathTotalLength+=len;
  }
}
function applyPathDistance(){
  if(!pathSegmentLengths||pathTotalLength<=0)return;
  pathDistance=((pathDistance%pathTotalLength)+pathTotalLength)%pathTotalLength;
  var remaining=pathDistance,segment=0;
  while(segment<pathSegmentLengths.length-1&&remaining>pathSegmentLengths[segment]){
    remaining-=pathSegmentLengths[segment++];
  }
  var len=pathSegmentLengths[segment];
  var frac=len>0?remaining/len:0;
  var p0=POSES[segment],p1=POSES[(segment+1)%POSES.length];
  var px=p0.px+(p1.px-p0.px)*frac;
  var py=p0.py+(p1.py-p0.py)*frac;
  var pz=p0.pz+(p1.pz-p0.pz)*frac;
  var fx=p0.fx+(p1.fx-p0.fx)*frac;
  var fy=p0.fy+(p1.fy-p0.fy)*frac;
  var fz=p0.fz+(p1.fz-p0.fz)*frac;
  var fl=Math.sqrt(fx*fx+fy*fy+fz*fz)||1;
  fx/=fl;fy/=fl;fz/=fl;
  // The recording matrices describe the opposite camera axis for this GS
  // viewer. Reverse it once, then add a small downward pitch so the path
  // view looks into the scene instead of at the back of the pose camera.
  fx=-fx;fy=-fy;fz=-fz;
  fy-=pathDownTilt;
  fl=Math.sqrt(fx*fx+fy*fy+fz*fz)||1;
  fx/=fl;fy/=fl;fz/=fl;
  var targetTheta=Math.atan2(fz,fx);
  var targetPhi=Math.acos(Math.max(-1,Math.min(1,fy)));
  var desiredX=px-fx*pathBackOffset;
  var desiredY=py-fy*pathBackOffset+pathUpOffset;
  var desiredZ=pz-fz*pathBackOffset;
  // Follow continuously while always choosing the shorter direction across +/- PI.
  var smoothing=0.15;
  if(arguments.length>0&&arguments[0]===true){
    tx=desiredX;ty=desiredY;tz=desiredZ;
    theta=targetTheta;phi=targetPhi;
  }else{
    tx+=(desiredX-tx)*smoothing;ty+=(desiredY-ty)*smoothing;tz+=(desiredZ-tz)*smoothing;
    theta+=shortestAngleDelta(theta,targetTheta)*smoothing;
    phi+=(targetPhi-phi)*smoothing;
  }
  applyCam();
}

// Path movement - called from Kotlin at 16ms intervals
window.movePath=function(dir){
  if(!POSES||POSES.length<2)return;
  var now=performance.now()/1000;
  var dt=lastPathTime===0?1/30:Math.min(now-lastPathTime,0.1);
  lastPathTime=now;
  pathDistance+=dir*pathSpeed*dt;
  applyPathDistance();
};

window.stopPath=function(){
  lastPathTime=0;
};

// Orbit swipe: simple theta/phi adjustment on sphere
window.swipeOrbit=function(dx,dy){
  if(pathMode!=='orbit'){pathMode='orbit';}
  if(!ORBIT){ORBIT={cx:orbitCenterX,cy:orbitCenterY,cz:orbitCenterZ,r:Math.max(0.1,radius/1.5)};}
  orbitCenterX=ORBIT.cx;orbitCenterY=ORBIT.cy;orbitCenterZ=ORBIT.cz;
  theta-=dx*0.005;
  phi=Math.max(0.05,Math.min(Math.PI-0.05,phi-(dy||0)*0.005));
  applyCam();
};

window.setMode=function(m){
  pathMode=m;
  if(m==='path'&&POSES){
    pathDistance=0;lastPathTime=0;
    applyPathDistance(true);
  }else if(m==='orbit'&&ORBIT){
    orbitUserDH=0;orbitUserDV=0;
    orbitCenterX=ORBIT.cx; orbitCenterY=ORBIT.cy; orbitCenterZ=ORBIT.cz;
    radius=ORBIT.r*1.5;
    theta=0; phi=Math.PI*0.4;
    applyCam();
  }
};

window.setOrbitData=function(data){
  ORBIT=data;
  if(ORBIT){
    ORBIT={cx:ORBIT.cx,cy:-ORBIT.cy,cz:-ORBIT.cz,r:ORBIT.r,nx:ORBIT.nx,ny:-ORBIT.ny,nz:-ORBIT.nz};
    if(pathMode==='orbit')setMode('orbit');
  }
};

window.setSpeed=function(s){pathSpeed=s;};

// Touch orbit (used in free mode + path/orbit right-half adjust)
var prevT=[],lastPinch=0,lastMX=0,lastMY=0;
function saveTouches(e){prevT=[];for(var i=0;i<e.touches.length;i++)prevT.push({x:e.touches[i].clientX,y:e.touches[i].clientY});}
canvas.addEventListener('touchstart',function(e){e.preventDefault();saveTouches(e);if(e.touches.length>=2){var dx=prevT[1].x-prevT[0].x,dy=prevT[1].y-prevT[0].y;lastPinch=Math.sqrt(dx*dx+dy*dy);lastMX=(prevT[0].x+prevT[1].x)/2;lastMY=(prevT[0].y+prevT[1].y)/2;}},{passive:false});
canvas.addEventListener('touchmove',function(e){e.preventDefault();if(e.touches.length===1&&prevT.length===1){var dx=e.touches[0].clientX-prevT[0].x,dy=e.touches[0].clientY-prevT[0].y;theta-=dx*0.005;phi-=dy*0.005;}else if(e.touches.length>=2&&prevT.length>=2){var pdx=e.touches[1].clientX-e.touches[0].clientX,pdy=e.touches[1].clientY-e.touches[0].clientY;var dist=Math.sqrt(pdx*pdx+pdy*pdy);if(lastPinch>0){radius*=lastPinch/dist;radius=Math.max(0.0001,Math.min(1e9,radius));}lastPinch=dist;var mx=(e.touches[0].clientX+e.touches[1].clientX)/2,my=(e.touches[0].clientY+e.touches[1].clientY)/2;if(lastMX||lastMY){var panDx=mx-lastMX,panDy=my-lastMY;var p=camPos();var fx=tx-p.x,fy=ty-p.y,fz=tz-p.z;var fl=Math.sqrt(fx*fx+fy*fy+fz*fz)||1;fx/=fl;fy/=fl;fz/=fl;var rx=-fz,ry=0,rz=fx,rl=Math.sqrt(rx*rx+rz*rz);if(rl>0.001){rx/=rl;rz/=rl;}else{rx=1;ry=0;rz=0;}var ux=ry*fz-rz*fy,uy=rz*fx-rx*fz,uz=rx*fy-ry*fx;var s=radius*0.001;tx-=(rx*panDx+ux*panDy)*s;ty-=(ry*panDx+uy*panDy)*s;tz-=(rz*panDx+uz*panDy)*s;}lastMX=mx;lastMY=my;}saveTouches(e);applyCam();},{passive:false});
canvas.addEventListener('touchend',function(e){saveTouches(e);if(e.touches.length<2){lastPinch=0;lastMX=0;lastMY=0;}});

// Compose-called functions
window.exportView=function(){return [theta,phi,radius,tx,ty,tz,pathDistance,pathMode].join(',');};
window.restoreView=function(state){var v=String(state).split(',');if(v.length<8)return;theta=+v[0];phi=+v[1];radius=+v[2];tx=+v[3];ty=+v[4];tz=+v[5];pathDistance=+v[6];pathMode=v[7];applyCam();};
window.resetView=function(){theta=initTheta;phi=initPhi;radius=initRadius;tx=initTx;ty=initTy;tz=initTz;pathDistance=0;applyCam();};
window.disposeViewer=function(){if(app){app.destroy();app=null;camEnt=null;}};
window.orbitView=function(dx,dy){
  theta-=dx*0.002;phi-=dy*0.002;applyCam();
};
window.zoomView=function(factor){radius*=factor;radius=Math.max(0.0001,Math.min(1e9,radius));applyCam();};
window.panView=function(dx,dy){
  var p=camPos();var st=Math.sin(theta),ct=Math.cos(theta),sp=Math.sin(phi),cp=Math.cos(phi);
  var rx=-st,ry=0,rz=ct;var ux=cp*ct,uy=-sp,uz=cp*st;var s=radius*0.001;
  tx-=(rx*dx+ux*dy)*s;ty-=(ry*dx+uy*dy)*s;tz-=(rz*dx+uz*dy)*s;applyCam();
};
window.moveCam=function(dx,dy,dz){
  var st=Math.sin(theta),ct=Math.cos(theta),sp=Math.sin(phi),cp=Math.cos(phi);
  var rx=-st,ry=0,rz=ct;var ux=cp*ct,uy=-sp,uz=cp*st;var fx=sp*ct,fy=cp,fz=sp*st;
  var s=radius*0.3;tx+=rx*dx*s+ux*dy*s+(-fx)*dz*s;ty+=ry*dx*s+uy*dy*s+(-fy)*dz*s;tz+=rz*dx*s+uz*dy*s+(-fz)*dz*s;applyCam();
};

if(typeof pc==='undefined'){loadingText.textContent='PlayCanvas not loaded';return;}
pc.createGraphicsDevice(canvas,{deviceTypes:[],antialias:false,depth:true,stencil:false,preserveDrawingBuffer:true,powerPreference:'high-performance'}).then(function(device){
  var ao=new pc.AppOptions();ao.graphicsDevice=device;
  ao.componentSystems=[pc.CameraComponentSystem,pc.LightComponentSystem,pc.RenderComponentSystem,pc.GSplatComponentSystem,pc.ScriptComponentSystem];
  ao.resourceHandlers=[pc.ContainerHandler,pc.TextureHandler,pc.GSplatHandler,pc.BinaryHandler];
  app=new pc.AppBase(canvas);app.init(ao);app.scene.ambientLight.set(0.5,0.5,0.5);
  var light=new pc.Entity('light');light.setEulerAngles(35,45,0);light.addComponent('light',{color:new pc.Color(1,0.98,0.96),intensity:1});app.root.addChild(light);
  camEnt=new pc.Entity('camera');camEnt.addComponent('camera',{clearColor:new pc.Color(0.067,0.067,0.2),nearClip:0.0001,farClip:10000});app.root.addChild(camEnt);
  app.start();app.autoRender=true;
  if(!PLY||PLY==='null'){loadingText.textContent='Processing...';loadingBarWrap.style.display='none';applyCam();}else{
    var asset=new pc.Asset('splat','gsplat',{url:PLY,filename:'model.ply'});
    asset.on('progress',function(rcv,len){var pct=Math.round(rcv/Math.max(1,len)*100);loadingText.textContent='Loading... '+pct+'%';loadingBar.style.width=pct+'%';});
    asset.on('load',function(){
      var ent=new pc.Entity('gsplat');ent.addComponent('gsplat',{asset:asset,unified:true});ent.setLocalEulerAngles(180,0,0);app.root.addChild(ent);
      try{var r=asset.resource;if(r&&r.splat){var s=r.splat;tx=s.centerX||0;ty=-(s.centerY||0);tz=-(s.centerZ||0);var hx=s.halfExtentsX||1,hy=s.halfExtentsY||1,hz=s.halfExtentsZ||1;var sz=Math.sqrt(hx*hx+hy*hy+hz*hz)*2;sceneRadius=Math.max(0.1,sz*0.5);radius=Math.max(0.1,sz*0.8);pathBackOffset=Math.max(sceneRadius*0.42,0.25);pathUpOffset=Math.max(sceneRadius*0.16,0.1);if(!ORBIT){ORBIT={cx:tx,cy:ty,cz:tz,r:sceneRadius};}}}catch(e){}
      initTheta=theta;initPhi=phi;initRadius=radius;initTx=tx;initTy=ty;initTz=tz;
      prepareClosedPath();
      if(pathMode==='orbit'&&ORBIT){setMode('orbit');}
      else if(pathMode==='path'&&POSES&&POSES.length>0){pathDistance=0;lastPathTime=0;applyPathDistance(true);}
      else{applyCam();}
      loadingEl.style.display='none';
    });
    asset.on('error',function(err){loadingText.textContent='GS failed: '+err;loadingBar.style.width='100%';loadingBar.style.background='rgba(255,100,100,0.6)';});
    app.assets.add(asset);app.assets.load(asset);
  }
}).catch(function(err){loadingText.textContent='Device error: '+err.message;});
})();
</script></body></html>"""
}
