package com.echo.phone.util

import android.util.Log

/**
 * 统一日志入口，logcat tag 固定为 "ECHO_PHONE"，便于 `adb logcat -s ECHO_PHONE` 精准过滤全链路。
 *
 * 覆盖：眼镜指令(START/STOP)、来自眼镜的帧/音频、后台会话与上传请求/结果，
 * 用于定位"眼镜选场景启动后后台无数据"的断点在哪一环。
 */
object EchoLog {
    const val TAG = "ECHO_PHONE"

    fun i(msg: String) = Log.i(TAG, msg)
    fun w(msg: String) = Log.w(TAG, msg)
    fun e(msg: String, t: Throwable? = null) = Log.e(TAG, msg, t)
}
