package com.echo.phone.ui.common

import com.echo.phone.domain.CameraPose
import org.junit.Assert.assertEquals
import org.junit.Test

class PathTraversalTest {
    @Test
    fun closedPathLengthIncludesTheReturnSegmentAndUsesTenSecondBaseline() {
        val poses = listOf(
            pose(0f, 0f, 0f),
            pose(3f, 0f, 0f),
            pose(3f, 4f, 0f),
        )

        assertEquals(12f, PathTraversal.closedLength(poses), 0.0001f)
        assertEquals(1.2f, PathTraversal.speedForTenSecondLoop(poses), 0.0001f)
    }

    @Test
    fun shortestAngularDeltaCrossesThePiBoundaryWithoutAFullTurn() {
        val from = Math.toRadians(179.0).toFloat()
        val to = Math.toRadians(-179.0).toFloat()

        assertEquals(Math.toRadians(2.0).toFloat(), PathTraversal.shortestAngularDelta(from, to), 0.0001f)
        assertEquals(-Math.toRadians(2.0).toFloat(), PathTraversal.shortestAngularDelta(to, from), 0.0001f)
    }

    private fun pose(x: Float, y: Float, z: Float) = CameraPose(
        position = floatArrayOf(x, y, z),
        rotation = floatArrayOf(),
        forward = floatArrayOf(0f, 0f, -1f),
    )
}
