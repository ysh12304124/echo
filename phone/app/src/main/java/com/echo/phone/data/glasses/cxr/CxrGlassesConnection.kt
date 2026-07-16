package com.echo.phone.data.glasses.cxr

import android.app.Activity
import android.content.Context
import android.content.Intent
import com.echo.phone.BuildConfig
import com.echo.phone.data.glasses.GlassesConnection
import com.echo.phone.data.glasses.GlassesConnectionException
import com.echo.phone.domain.*
import com.echo.phone.util.EchoLog
import com.rokid.cxr.Caps
import com.rokid.cxr.link.CXRLink
import com.rokid.cxr.link.callbacks.ICXRSessionCbk
import com.rokid.cxr.link.callbacks.ICustomCmdCbk
import com.rokid.cxr.link.callbacks.IGlassAppCbk
import com.rokid.cxr.link.utils.CxrDefs
import com.rokid.sprite.aiapp.externalapp.auth.AuthResult
import com.rokid.sprite.aiapp.externalapp.auth.AuthorizationHelper
import com.rokid.sprite.aiapp.externalapp.auth.GlassPermission
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import java.lang.ref.WeakReference

/**
 * 基于 Rokid CXR-L SDK 的眼镜连接实现（手机端主导）。
 *
 * 链路：鉴权（Rokid AI App）→ 建 CustomApp 会话 → 等链路+蓝牙就绪 → appStart 拉起眼镜端 Echo App
 *      → 订阅自定义指令。眼镜端仅录制视频(无拍照/无录音)，边录边把分片经 rk_custom_key 推送给手机，
 *      手机不落地直接转发后台，见 [videoChunkFlow]；IMU（空间记忆开启时）经 rk_custom_key → [imuFlow]；
 *      START/STOP 场景指令经 rk_custom_key → [commands]。
 *
 * 鉴权需 Activity 与 onActivityResult 配合：Activity 侧调用 [attachActivity] 与 [onAuthResult]。
 */
class CxrGlassesConnection(
    private val appContext: Context,
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Default),
) : GlassesConnection {

    companion object {
        private const val TAG = "CxrGlasses"
        const val REQUEST_CODE_AUTH = 0xEC01
        private const val READY_TIMEOUT_MS = 20_000L
        // 等待 CustomApp 会话「可用」(onSessionAvailable) 的超时。
        private const val SESSION_AVAILABLE_TIMEOUT_MS = 15_000L
        // 等待 appStart 回调 / 会话「开始」(onSessionStart) 的超时。
        private const val APP_START_TIMEOUT_MS = 10_000L
    }

    private val _connectionState = MutableStateFlow(GlassesConnectionState.DISCONNECTED)
    override val connectionState = _connectionState.asStateFlow()

    private val _deviceStatus = MutableStateFlow(DeviceStatus(connected = false))
    override val deviceStatus = _deviceStatus.asStateFlow()

    private val _videoChunkFlow = MutableSharedFlow<VideoChunk>(extraBufferCapacity = 256)
    override val videoChunkFlow = _videoChunkFlow.asSharedFlow()

    private val _imuFlow = MutableSharedFlow<ImuSample>(extraBufferCapacity = 256)
    override val imuFlow = _imuFlow.asSharedFlow()

    private val _commands = MutableSharedFlow<GlassCommand>(extraBufferCapacity = 16)
    override val commands = _commands.asSharedFlow()

    private var cxrLink: CXRLink? = null
    private var connecting = false
    private var activityRef: WeakReference<Activity>? = null
    private var authDeferred: CompletableDeferred<String>? = null

    // CustomApp 会话生命周期（来自 ICXRSessionCbk）：available=眼镜侧就绪可拉起；started=CustomApp 已连接、指令通道就绪。
    private val sessionAvailable = MutableStateFlow(false)
    private val sessionStarted = MutableStateFlow(false)

    private val sessionCbk = object : ICXRSessionCbk {
        override fun onSessionAvailable(reason: CxrDefs.CXRSessionReason?) {
            EchoLog.i("CXR 会话可用 onSessionAvailable reason=$reason（可 appStart 拉起 CustomApp）")
            sessionAvailable.value = true
        }

        override fun onSessionStart(reason: CxrDefs.CXRSessionReason?) {
            EchoLog.i("CXR 会话已开始 onSessionStart reason=$reason（CustomApp 已连接，指令通道就绪）")
            sessionStarted.value = true
        }

        override fun onSessionPause(reason: CxrDefs.CXRSessionReason?) {
            EchoLog.w("CXR 会话暂停 onSessionPause reason=$reason")
            sessionStarted.value = false
        }

        override fun onSessionUnavailable(reason: CxrDefs.CXRSessionReason?) {
            EchoLog.w("CXR 会话不可用 onSessionUnavailable reason=$reason")
            sessionAvailable.value = false
            sessionStarted.value = false
        }
    }

    // ---- Activity 绑定与鉴权回调（由 MainActivity 调用）----

    fun attachActivity(activity: Activity) {
        activityRef = WeakReference(activity)
    }

    fun onAuthResult(resultCode: Int, data: Intent?) {
        val deferred = authDeferred ?: return
        when (val result = AuthorizationHelper.parseAuthorizationResult(resultCode, data)) {
            is AuthResult.AuthSuccess ->
                if (result.token.isNotBlank()) deferred.complete(result.token)
                else deferred.completeExceptionally(GlassesConnectionException("鉴权失败：token 为空"))
            is AuthResult.AuthFail -> deferred.completeExceptionally(GlassesConnectionException("鉴权失败"))
            is AuthResult.AuthCancel -> deferred.completeExceptionally(GlassesConnectionException("鉴权已取消"))
        }
    }

    // ---- 连接生命周期 ----

    override suspend fun connect() {
        if (connecting) { EchoLog.w("already connecting"); return }
        if (_connectionState.value == GlassesConnectionState.CONNECTED ||
            _connectionState.value == GlassesConnectionState.RECORDING
        ) {
            // HomeScreen 的 LaunchedEffect(Unit) 在每次重新进入首页 Tab 时都会调用 connectGlasses()；
            // 若不在此拦截，会重复创建 CXRLink 并把同一个 customCmdCallback 注册到多条链路上，
            // 导致眼镜端每条指令（尤其是 video_chunk/video_end）被收到并处理多次。
            EchoLog.i("已处于连接状态(${_connectionState.value})，忽略重复 connect()")
            return
        }
        connecting = true
        val activity = activityRef?.get()
            ?: throw GlassesConnectionException("请在 Echo 应用前台发起连接")
        if (!AuthorizationHelper.isRequiredRokidAppInstalled(activity) &&
            !AuthorizationHelper.isRequiredHiRokidInstalled(activity)
        ) {
            throw GlassesConnectionException("未检测到 Rokid AI App（≥1.9.0），请先安装并配对眼镜")
        }

        _connectionState.value = GlassesConnectionState.CONNECTING
        EchoLog.i("开始连接眼镜(CXR-L)…")
        try {
            val token = authenticate(activity)
            EchoLog.i("鉴权通过，建立 CXR 会话")
            createSessionAndConnect(token)
            awaitReady()
            EchoLog.i("链路就绪(CXR/蓝牙已连接)")
            ensureGlassAppRunning()
            registerCapabilityCallbacks()
            EchoLog.i("已注册自定义指令回调，眼镜连接完成")
        connecting = false
            _connectionState.value = GlassesConnectionState.CONNECTED
            _deviceStatus.value = DeviceStatus(connected = true, batteryPercent = CxrLinkHub.batteryPercent.value)
            observeDeviceState()
            sendGlassStatus("待机")
        } catch (e: Exception) {
            EchoLog.e("连接眼镜失败: ${e.message}", e)
            connecting = false
            _connectionState.value = GlassesConnectionState.DISCONNECTED
            _deviceStatus.value = DeviceStatus(connected = false)
            throw if (e is GlassesConnectionException) e
            else GlassesConnectionException("连接眼镜失败：${e.message}")
        }
    }

    private suspend fun authenticate(activity: Activity): String {
        val deferred = CompletableDeferred<String>()
        authDeferred = deferred
        val cached = AuthorizationHelper.requestAuthorization(
            activity,
            arrayOf(GlassPermission.MICROPHONE, GlassPermission.CAMERA, GlassPermission.MEDIA),
            REQUEST_CODE_AUTH,
        )
        if (cached != null) {
            onAuthResult(cached.first, cached.second)
        }
        return try {
            withTimeout(60_000L) { deferred.await() }
        } catch (e: TimeoutCancellationException) {
            throw GlassesConnectionException("鉴权超时")
        } finally {
            authDeferred = null
        }
    }

    private fun createSessionAndConnect(token: String) {
        CxrLinkHub.reset()
        sessionAvailable.value = false
        sessionStarted.value = false
        val link = CXRLink(appContext).apply {
            // 传入会话回调，才能拿到 CustomApp 会话的 available/start/pause/unavailable 生命周期。
            configCXRSession(
                CxrDefs.CXRSession(CxrDefs.CXRSessionType.CUSTOMAPP, BuildConfig.GLASS_APP_PACKAGE),
                sessionCbk,
            )
            setCXRLinkCbk(CxrLinkHub.linkCallback)
        }
        cxrLink = link
        link.connect(token)
    }

    private suspend fun awaitReady() {
        try {
            withTimeout(READY_TIMEOUT_MS) {
                while (!CxrLinkHub.sessionReady) delay(150)
            }
        } catch (e: TimeoutCancellationException) {
            throw GlassesConnectionException("链路未就绪（CXR/蓝牙未连接），请检查眼镜配对状态")
        }
    }

    private suspend fun ensureGlassAppRunning() {
        val link = cxrLink ?: throw GlassesConnectionException("链路未创建")

        // CustomApp 需由手机端在「会话可用」后 appStart 拉起，眼镜端 CustomApp 才会加入本会话、
        // 其 CXRServiceBridge 才会回调 onConnected 并让 sendMessage(rk_custom_key) 生效。
        // appStart 若在会话可用前调用，openApp 不会真正下发（onOpenAppResult 也不回调）。
        val available = runCatching {
            withTimeout(SESSION_AVAILABLE_TIMEOUT_MS) { sessionAvailable.first { it } }
        }.isSuccess
        EchoLog.i("等待 CXR 会话可用(onSessionAvailable) 结果=$available")

        val entry = "${BuildConfig.GLASS_APP_PACKAGE}${BuildConfig.GLASS_APP_ENTRY}"
        val openedDeferred = CompletableDeferred<Boolean>()
        EchoLog.i("appStart 拉起眼镜端 Echo entry=$entry")
        link.appStart(entry, object : IGlassAppCbk {
            override fun onInstallAppResult(success: Boolean) {}
            override fun onUnInstallAppResult(success: Boolean) {}
            override fun onOpenAppResult(success: Boolean) {
                EchoLog.i("appStart 回调 onOpenAppResult=$success")
                if (!openedDeferred.isCompleted) openedDeferred.complete(success)
            }
            override fun onStopAppResult(success: Boolean) {}
            override fun onGlassAppResume(resumed: Boolean) {
                EchoLog.i("appStart 回调 onGlassAppResume=$resumed")
            }
            override fun onQueryAppResult(installed: Boolean) {}
        })
        val opened = runCatching { withTimeout(APP_START_TIMEOUT_MS) { openedDeferred.await() } }
            .getOrDefault(false)
        EchoLog.i("appStart 完成 opened=$opened")

        // 会话真正「开始」后，眼镜端 CustomApp 已连接、指令通道就绪。
        val started = runCatching {
            withTimeout(APP_START_TIMEOUT_MS) { sessionStarted.first { it } }
        }.isSuccess
        EchoLog.i("等待 CXR 会话开始(onSessionStart) 结果=$started")
        if (!started) {
            EchoLog.w("会话未进入 started：眼镜端可能未显示「手机已连接」，指令(START/STOP)可能发不出，请重连或确认眼镜端 Echo 已安装")
        }
    }

    private fun registerCapabilityCallbacks() {
        val link = cxrLink ?: return
        link.setCXRCustomCmdCbk(customCmdCallback)
        runCatching { link.getGlassDeviceInfo() }
    }

    private fun observeDeviceState() {
        scope.launch {
            CxrLinkHub.batteryPercent.collect { pct ->
                _deviceStatus.value = _deviceStatus.value.copy(batteryPercent = pct)
            }
        }
        scope.launch {
            CxrLinkHub.btConnected.collect { bt ->
                if (!bt && _connectionState.value != GlassesConnectionState.DISCONNECTED) {
                    _deviceStatus.value = _deviceStatus.value.copy(connected = false)
                    _connectionState.value = GlassesConnectionState.DISCONNECTED
                }
            }
        }
    }

    override suspend fun disconnect() {
        val link = cxrLink
        runCatching { link?.appStop(noopAppCbk) }
        runCatching { link?.disconnect() }
        cxrLink = null
        CxrLinkHub.reset()
        _connectionState.value = GlassesConnectionState.DISCONNECTED
        _deviceStatus.value = DeviceStatus(connected = false)
    }

    // ---- 录制控制 ----

    override suspend fun startTimeRecording(scene: TimeScene, partition: DataPartition) {
        cxrLink ?: throw GlassesConnectionException("眼镜未连接")
        _connectionState.value = GlassesConnectionState.RECORDING
        _deviceStatus.value = _deviceStatus.value.copy(isRecordingTime = true)
        sendGlassStatus("记忆中")
    }

    override suspend fun stopRecording() {
        _deviceStatus.value = _deviceStatus.value.copy(isRecordingTime = false)
        _connectionState.value = GlassesConnectionState.CONNECTED
        sendGlassStatus("待机")
    }

    /** 向眼镜端 CustomApp 推送状态文案，在镜片显示（待机/记忆中/…）。 */
    private fun sendGlassStatus(text: String) {
        runCatching {
            cxrLink?.sendCustomCmd(
                "rk_custom_client",
                Caps().apply { write("status"); write(text) },
            )
        }
    }

    override suspend fun sendMemoryComplete(sid: String) {
        runCatching {
            cxrLink?.sendCustomCmd(
                "rk_custom_client",
                Caps().apply { write("memory_complete"); write(sid) },
            )
        }
    }

    // ---- SDK 回调 ----

    private val customCmdCallback = object : ICustomCmdCbk {
        override fun onCustomCmdResult(key: String?, payload: ByteArray?) {
            if (key != "rk_custom_key" || payload == null) return
            val caps = runCatching { Caps.fromBytes(payload) }.getOrNull()
            if (caps == null) {
                EchoLog.w("眼镜指令 Caps 解析失败")
                return
            }
            val tag = caps.at(0).let { if (it.type() == Caps.Value.TYPE_STRING) it.string else null }
            when {
                tag == "imu" && caps.size() >= 8 -> {
                    val sample = parseImuSample(caps)
                    if (sample != null) _imuFlow.tryEmit(sample)
                }
                tag == "video_chunk" && caps.size() >= 4 -> handleVideoChunk(caps)
                tag == "video_patch" && caps.size() >= 4 -> handleVideoPatch(caps)
                tag == "video_end" && caps.size() >= 3 -> handleVideoEnd(caps)
                else -> {
                    val command = parseCommand(caps)
                    if (command == null) {
                        EchoLog.w("眼镜指令无法识别为 START/STOP")
                    } else {
                        EchoLog.i("解析眼镜指令成功 ${command.type} scene=${command.scene} sid=${command.glassSid}")
                        _commands.tryEmit(command)
                    }
                }
            }
        }
    }

    /**
     * 眼镜端约定：
     * - Caps = ["cmd", "START"|"STOP", (scene?), (sid?)]。START 携带场景名与 sid；STOP 仅携带 sid。
     * - Caps = ["video_chunk", sid, index, base64]，边录边发的视频分片。
     * - Caps = ["video_patch", sid, offset, base64]，MediaRecorder 结束时回改的文件头覆盖，必须在 video_end 之前处理。
     * - Caps = ["video_end", sid, filename]，视频录制结束。
     */

    private fun handleVideoChunk(caps: Caps) {
        try {
            val sid = caps.at(1).string ?: return
            val idx = caps.at(2).string?.toIntOrNull() ?: return
            val b64 = caps.at(3).string ?: return
            val data = android.util.Base64.decode(b64, android.util.Base64.DEFAULT)
            _videoChunkFlow.tryEmit(VideoChunk.Data(sid, idx, data))
        } catch (e: Exception) { EchoLog.e("视频分片解析失败: " + e.message, e) }
    }

    private fun handleVideoPatch(caps: Caps) {
        try {
            val sid = caps.at(1).string ?: return
            val offset = caps.at(2).string?.toLongOrNull() ?: return
            val b64 = caps.at(3).string ?: return
            val data = android.util.Base64.decode(b64, android.util.Base64.DEFAULT)
            EchoLog.i("收到眼镜 video_patch sid=$sid offset=$offset bytes=${data.size}")
            _videoChunkFlow.tryEmit(VideoChunk.Patch(sid, offset, data))
        } catch (e: Exception) { EchoLog.e("video_patch 解析失败: " + e.message, e) }
    }

    private fun handleVideoEnd(caps: Caps) {
        try {
            val sid = caps.at(1).string ?: return
            val filename = caps.at(2).string ?: "unknown.mp4"
            EchoLog.i("收到眼镜 video_end sid=$sid filename=$filename")
            _videoChunkFlow.tryEmit(VideoChunk.End(sid, filename))
        } catch (e: Exception) { EchoLog.e("video_end 解析失败: " + e.message, e) }
    }

    private fun parseImuSample(caps: Caps): ImuSample? {
        return try {
            val values = (0 until caps.size()).mapNotNull { i ->
                val v = caps.at(i)
                if (v.type() == Caps.Value.TYPE_STRING) v.string else null
            }
            if (values.size < 8 || values[0] != "imu") return null
            ImuSample(
                ax = values[1].toFloat(), ay = values[2].toFloat(), az = values[3].toFloat(),
                gx = values[4].toFloat(), gy = values[5].toFloat(), gz = values[6].toFloat(),
                timestampMs = values[7].toLong(),
            )
        } catch (_: Exception) { null }
    }

    private fun parseCommand(caps: Caps): GlassCommand? {
        val values = (0 until caps.size()).mapNotNull { i ->
            val v = caps.at(i)
            if (v.type() == Caps.Value.TYPE_STRING) v.string else null
        }
        // 第一个值为标签 "cmd"，其后为指令、可选场景、可选 sid。
        val tokens = if (values.firstOrNull().equals("cmd", ignoreCase = true)) values.drop(1) else values
        return when (tokens.getOrNull(0)?.uppercase()) {
            "START" -> {
                val scene = tokens.getOrNull(1)?.let { name ->
                    runCatching { TimeScene.valueOf(name.uppercase()) }.getOrNull()
                }
                val sid = tokens.getOrNull(2)
                GlassCommand(GlassCommandType.START, scene, sid)
            }
            "STOP" -> {
                val sid = tokens.getOrNull(1)
                GlassCommand(GlassCommandType.STOP, null, sid)
            }
            else -> null
        }
    }

    private val noopAppCbk = object : IGlassAppCbk {
        override fun onInstallAppResult(success: Boolean) {}
        override fun onUnInstallAppResult(success: Boolean) {}
        override fun onOpenAppResult(success: Boolean) {}
        override fun onStopAppResult(success: Boolean) {}
        override fun onGlassAppResume(resumed: Boolean) {}
        override fun onQueryAppResult(installed: Boolean) {}
    }
}
