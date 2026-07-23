package com.echo.phone.util

import android.content.Context
import android.util.Log
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

/**
 * 统一日志入口，logcat tag 固定为 "ECHO_PHONE"，便于 `adb logcat -s ECHO_PHONE` 精准过滤全链路。
 *
 * 覆盖：眼镜指令(START/STOP)、来自眼镜的帧/音频、后台会话与上传请求/结果，
 * 用于定位"眼镜选场景启动后后台无数据"的断点在哪一环。
 *
 * 除了写 logcat，同时落一份文件日志到应用外部存储目录下的 echo_phone.log：
 * logcat 缓冲区容量有限且随进程重启/被系统杀死而失去历史，若排查时进程已不在运行、
 * 或查看时机与事件发生时机之间缓冲区已被系统日志刷掉，就会出现"tag 下完全看不到输出"的假象。
 * 文件日志不受这些限制，可随时通过 `adb pull` 取出全量历史，便于事后排查。
 */
object EchoLog {
    const val TAG = "ECHO_PHONE"

    private val dateFmt = SimpleDateFormat("MM-dd HH:mm:ss.SSS", Locale.CHINA)
    private val ioExecutor = Executors.newSingleThreadExecutor()
    @Volatile private var logFile: File? = null
    @Volatile private var crashHandlerInstalled = false

    /** 需在 Application.onCreate 最早处调用一次，之后才会落文件日志(仍会正常写 logcat)。 */
    fun init(context: Context) {
        if (logFile != null) return
        try {
            val dir = context.getExternalFilesDir(null) ?: context.filesDir
            val f = File(dir, "echo_phone.log")
            logFile = f
            append("===== app start pid=${android.os.Process.myPid()} =====")
            installCrashHandler()
        } catch (e: Exception) {
            Log.e(TAG, "EchoLog.init failed: ${e.message}")
        }
    }

    fun i(msg: String) { Log.i(TAG, msg); append("I $msg") }
    fun w(msg: String) { Log.w(TAG, msg); append("W $msg") }
    fun e(msg: String, t: Throwable? = null) { Log.e(TAG, msg, t); append("E $msg${if (t != null) " " + Log.getStackTraceString(t) else ""}") }
    fun logFilePath(): String = logFile?.absolutePath ?: "日志尚未初始化"

    fun recentLines(maxLines: Int = 120): String {
        val f = logFile ?: return "日志尚未初始化"
        return try {
            if (!f.exists()) return "暂无日志"
            f.readLines().takeLast(maxLines).joinToString("\n").ifBlank { "暂无日志" }
        } catch (e: IOException) {
            "读取日志失败: ${e.message}"
        } catch (e: SecurityException) {
            "读取日志失败: ${e.message}"
        }
    }

    fun clear() {
        val f = logFile ?: return
        try {
            FileOutputStream(f, false).use {
                it.write("${dateFmt.format(Date())} ===== log cleared =====\n".toByteArray())
            }
        } catch (e: Exception) {
            Log.e(TAG, "EchoLog.clear failed: ${e.message}")
        }
    }

    private fun installCrashHandler() {
        if (crashHandlerInstalled) return
        crashHandlerInstalled = true
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            val stack = Log.getStackTraceString(throwable)
            val line = "F uncaught thread=${thread.name} ${throwable.javaClass.name}: ${throwable.message}\n$stack"
            Log.e(TAG, line)
            appendSync(line)
            previous?.uncaughtException(thread, throwable)
        }
    }

    private fun append(line: String) {
        val f = logFile ?: return
        val stamped = "${dateFmt.format(Date())} $line\n"
        ioExecutor.execute {
            try {
                FileOutputStream(f, true).use { it.write(stamped.toByteArray()) }
            } catch (_: Exception) {
                // 文件写入失败不应影响主流程，忽略即可(logcat 一路仍正常)。
            }
        }
    }

    private fun appendSync(line: String) {
        val f = logFile ?: return
        val stamped = "${dateFmt.format(Date())} $line\n"
        try {
            FileOutputStream(f, true).use { it.write(stamped.toByteArray()) }
        } catch (_: Exception) {
        }
    }
}
