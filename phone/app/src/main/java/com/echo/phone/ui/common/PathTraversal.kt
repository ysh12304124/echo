package com.echo.phone.ui.common

import com.echo.phone.domain.CameraPose
import kotlin.math.PI
import kotlin.math.sqrt

internal object PathTraversal {
    private const val LoopDurationSeconds = 10f

    fun closedLength(poses: List<CameraPose>): Float {
        if (poses.size < 2) return 0f
        return poses.indices.sumOf { index ->
            val from = poses[index].position
            val to = poses[(index + 1) % poses.size].position
            distance(from, to).toDouble()
        }.toFloat()
    }

    fun speedForTenSecondLoop(poses: List<CameraPose>): Float =
        closedLength(poses) / LoopDurationSeconds

    fun shortestAngularDelta(from: Float, to: Float): Float {
        val fullTurn = (2 * PI).toFloat()
        return ((to - from + PI.toFloat()) % fullTurn + fullTurn) % fullTurn - PI.toFloat()
    }

    private fun distance(from: FloatArray, to: FloatArray): Float {
        val dx = to[0] - from[0]
        val dy = to[1] - from[1]
        val dz = to[2] - from[2]
        return sqrt(dx * dx + dy * dy + dz * dz)
    }
}
