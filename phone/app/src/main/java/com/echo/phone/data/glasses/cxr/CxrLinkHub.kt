package com.echo.phone.data.glasses.cxr

import android.util.Log
import com.rokid.cxr.link.callbacks.ICXRLinkCbk
import com.rokid.cxr.link.utils.GlassInfo
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 进程内唯一的 [ICXRLinkCbk]，集中收敛 CXR 链路与蓝牙连接状态、眼镜设备信息。
 *
 * 对齐官方 Sample 的 CxrLinkConnectionHub：在会话创建时 setCXRLinkCbk 注册本回调，
 * 其余模块只订阅这里的 StateFlow，避免多处覆盖 SDK 回调。
 */
object CxrLinkHub {
    private const val TAG = "CxrLinkHub"

    private val _cxrlConnected = MutableStateFlow(false)
    val cxrlConnected: StateFlow<Boolean> = _cxrlConnected.asStateFlow()

    private val _btConnected = MutableStateFlow(false)
    val btConnected: StateFlow<Boolean> = _btConnected.asStateFlow()

    private val _batteryPercent = MutableStateFlow(0)
    val batteryPercent: StateFlow<Int> = _batteryPercent.asStateFlow()

    private val _charging = MutableStateFlow(false)
    val charging: StateFlow<Boolean> = _charging.asStateFlow()

    private val _brightness = MutableStateFlow(8)
    val brightness: StateFlow<Int> = _brightness.asStateFlow()

    private val _volume = MutableStateFlow(10)
    val volume: StateFlow<Int> = _volume.asStateFlow()

    /** 链路 + 蓝牙均就绪时为 true（能力可用前提）。 */
    val sessionReady: Boolean
        get() = _cxrlConnected.value && _btConnected.value

    val linkCallback: ICXRLinkCbk = object : ICXRLinkCbk {
        override fun onCXRLConnected(connected: Boolean) {
            Log.i(TAG, "onCXRLConnected=$connected")
            _cxrlConnected.value = connected
        }

        override fun onGlassBtConnected(connected: Boolean) {
            Log.i(TAG, "onGlassBtConnected=$connected")
            _btConnected.value = connected
        }

        override fun onGlassAiAssistStart() {}
        override fun onGlassAiAssistStop() {}
        override fun onGlassAiInterrupt(interruptWake: Boolean) {}

        override fun onGlassDeviceInfo(deviceInfo: GlassInfo) {
            Log.d(TAG, "onGlassDeviceInfo=$deviceInfo")
            _brightness.value = deviceInfo.brightness
            _volume.value = deviceInfo.sound
            _batteryPercent.value = deviceInfo.batteryLevel
            _charging.value = deviceInfo.ischarging
        }

        override fun onGlassWearingStatus(wearing: Boolean) {}
    }

    fun reset() {
        _cxrlConnected.value = false
        _btConnected.value = false
        _batteryPercent.value = 0
        _charging.value = false
        _brightness.value = 8
        _volume.value = 10
    }
}
