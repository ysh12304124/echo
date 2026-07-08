package com.echo.glasses.receiver

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Rokid 眼镜镜腿键 / 触控板系统广播动作。
 *
 * 参考 CXR-L 文档"眼镜端按键与系统广播"：在 [com.echo.glasses.MainActivity] 中动态注册，
 * 事件回调给 App 后经 CXR-S sendMessage("rk_custom_key") 上报手机端。
 * [abortBroadcast] 阻止其它接收者重复处理。
 */
enum class KeyType(val action: String) {
    CLICK("com.android.action.ACTION_SPRITE_BUTTON_CLICK"),
    BUTTON_DOWN("com.android.action.ACTION_SPRITE_BUTTON_DOWN"),
    BUTTON_UP("com.android.action.ACTION_SPRITE_BUTTON_UP"),
    DOUBLE_CLICK("com.android.action.ACTION_SPRITE_BUTTON_DOUBLE_CLICK"),
    LONG_PRESS("com.android.action.ACTION_SPRITE_BUTTON_LONG_PRESS"),
    AI_START("com.android.action.ACTION_AI_START"),
    TWO_FINGER_SINGLE_TAP("com.android.action.ACTION_TWO_FINGER_SINGLE_TAP"),
    TWO_FINGER_DOUBLE_TAP("com.android.action.ACTION_TWO_FINGER_DOUBLE_TAP"),
    TWO_FINGER_SWIPE_FORWARD("com.android.action.ACTION_TWO_FINGER_SWIPE_FORWARD"),
    TWO_FINGER_SWIPE_BACK("com.android.action.ACTION_TWO_FINGER_SWIPE_BACK"),
    SETTINGS_KEY("com.android.action.ACTION_SETTINGS_KEY"),
}

fun interface KeyEventListener {
    fun onKeyEvent(keyType: KeyType)
}

class KeyReceiver(private val listener: KeyEventListener) : BroadcastReceiver() {
    override fun onReceive(context: Context?, intent: Intent?) {
        val action = intent?.action ?: return
        val type = KeyType.entries.firstOrNull { it.action == action } ?: return
        listener.onKeyEvent(type)
        abortBroadcast()
    }
}
