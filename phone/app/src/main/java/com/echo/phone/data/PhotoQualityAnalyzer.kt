package com.echo.phone.data

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import kotlin.math.abs
import kotlin.math.sqrt

/**
 * 照片质量实时分析：模糊度（Laplacian 方差）、亮度、运动速度。
 *
 * 用于空间记忆录制时即时反馈给用户。
 * 所有方法返回 QualityResult，包含是否需要提示和提示文案。
 */
data class QualityResult(
    val isBlurry: Boolean = false,
    val isTooDark: Boolean = false,
    val isTooFast: Boolean = false,
    val blurScore: Float = 0f,
    val brightness: Float = 0f,
    val gyroSpeed: Float = 0f,
) {
    fun feedback(): String? = when {
        isBlurry -> "画面模糊，请保持稳定"
        isTooDark -> "光线不足，请补充照明"
        isTooFast -> "请慢一点移动"
        else -> null
    }
}

class PhotoQualityAnalyzer {
    private var lastGyroTime = 0L
    private var lastFeedbackTime = mutableMapOf<String, Long>()
    private val feedbackCooldownMs = 3_000L

    companion object {
        const val BLUR_THRESHOLD = 50f   // Laplacian 方差低于此值视为模糊
        const val DARK_THRESHOLD = 60f    // 平均灰度低于此值视为过暗
        const val GYRO_SPEED_THRESHOLD = 1.5f // rad/s 角速度和超过此值视为过快
    }

    /** 从 JPEG 字节数组分析模糊度和亮度。 */
    fun analyzeImage(jpegData: ByteArray): QualityResult {
        val bmp = runCatching { BitmapFactory.decodeByteArray(jpegData, 0, jpegData.size) }
            .getOrNull() ?: return QualityResult()

        // 缩放到 256px 宽以加速
        val w = bmp.width; val h = bmp.height
        val scale = 256f / w.coerceAtMost(h)
        val small = Bitmap.createScaledBitmap(bmp, (w * scale).toInt(), (h * scale).toInt(), true)
        bmp.recycle()

        val blurScore = laplacianVariance(small)
        val brightness = averageBrightness(small)
        small.recycle()

        return QualityResult(
            isBlurry = blurScore < BLUR_THRESHOLD,
            isTooDark = brightness < DARK_THRESHOLD,
            blurScore = blurScore,
            brightness = brightness,
        )
    }

    /** IMU 运动速度分析。返回是否需要慢一点提示。 */
    fun analyzeMotion(gx: Float, gy: Float, gz: Float, timestampMs: Long): QualityResult {
        val speed = sqrt(gx * gx + gy * gy + gz * gz)
        lastGyroTime = timestampMs
        return QualityResult(
            isTooFast = speed > GYRO_SPEED_THRESHOLD,
            gyroSpeed = speed,
        )
    }

    /**
     * 综合判断并返回用户反馈文案。
     * 同类型反馈有 3 秒冷却期，避免频繁刷屏。
     */
    fun evaluate(imageResult: QualityResult, motionResult: QualityResult): String? {
        val merged = QualityResult(
            isBlurry = imageResult.isBlurry,
            isTooDark = imageResult.isTooDark,
            isTooFast = motionResult.isTooFast,
        )
        val msg = merged.feedback() ?: return null

        val now = System.currentTimeMillis()
        val key = when {
            merged.isBlurry -> "blur"
            merged.isTooDark -> "dark"
            merged.isTooFast -> "speed"
            else -> return null
        }
        val last = lastFeedbackTime[key] ?: 0L
        if (now - last < feedbackCooldownMs) return null
        lastFeedbackTime[key] = now
        return msg
    }

    // ---- 图像分析算法 ----

    /** Laplacian 方差：衡量图像清晰度，值越高越清晰。 */
    private fun laplacianVariance(bmp: Bitmap): Float {
        val w = bmp.width; val h = bmp.height
        val kernel = intArrayOf(0, 1, 0, 1, -4, 1, 0, 1, 0)
        val pixels = IntArray(w * h)
        bmp.getPixels(pixels, 0, w, 0, 0, w, h)
        val gray = IntArray(w * h) { i ->
            val p = pixels[i]
            ((p shr 16 and 0xFF) * 0.299 + (p shr 8 and 0xFF) * 0.587 + (p and 0xFF) * 0.114).toInt()
        }
        var sum = 0f; var count = 0
        for (y in 1 until h - 1) {
            for (x in 1 until w - 1) {
                var lap = 0
                for (ky in 0..2) for (kx in 0..2) {
                    lap += gray[(y + ky - 1) * w + (x + kx - 1)] * kernel[ky * 3 + kx]
                }
                sum += abs(lap).toFloat()
                count++
            }
        }
        return if (count > 0) sum / count else 0f
    }

    /** 平均灰度值：0=全黑, 255=全白。 */
    private fun averageBrightness(bmp: Bitmap): Float {
        val w = bmp.width; val h = bmp.height
        val pixels = IntArray(w * h)
        bmp.getPixels(pixels, 0, w, 0, 0, w, h)
        var sum = 0L
        for (p in pixels) {
            val r = (p shr 16) and 0xFF
            val g = (p shr 8) and 0xFF
            val b = p and 0xFF
            sum += (0.299 * r + 0.587 * g + 0.114 * b).toLong()
        }
        return sum.toFloat() / pixels.size
    }
}
