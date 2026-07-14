package com.echo.phone.data.spatial

import com.echo.phone.domain.ImuSample
import kotlin.math.abs
import kotlin.math.acos
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

data class PoseVector(val x: Double, val y: Double, val z: Double) {
    operator fun plus(other: PoseVector) = PoseVector(x + other.x, y + other.y, z + other.z)
    operator fun minus(other: PoseVector) = PoseVector(x - other.x, y - other.y, z - other.z)
    operator fun times(value: Double) = PoseVector(x * value, y * value, z * value)
    fun length() = sqrt(x * x + y * y + z * z)
}

data class PoseQuaternion(val w: Double, val x: Double, val y: Double, val z: Double) {
    fun normalized(): PoseQuaternion {
        val length = sqrt(w * w + x * x + y * y + z * z).coerceAtLeast(1e-12)
        return PoseQuaternion(w / length, x / length, y / length, z / length)
    }

    fun conjugate() = PoseQuaternion(w, -x, -y, -z)

    operator fun times(other: PoseQuaternion) = PoseQuaternion(
        w * other.w - x * other.x - y * other.y - z * other.z,
        w * other.x + x * other.w + y * other.z - z * other.y,
        w * other.y - x * other.z + y * other.w + z * other.x,
        w * other.z + x * other.y - y * other.x + z * other.w,
    )

    fun rotate(vector: PoseVector): PoseVector {
        val rotated = this * PoseQuaternion(0.0, vector.x, vector.y, vector.z) * conjugate()
        return PoseVector(rotated.x, rotated.y, rotated.z)
    }

    fun angleTo(other: PoseQuaternion): Double {
        val dot = abs(w * other.w + x * other.x + y * other.y + z * other.z)
            .coerceIn(-1.0, 1.0)
        return Math.toDegrees(2.0 * acos(dot))
    }
}

data class FramePose(
    val frameTimestampMs: Long,
    val position: PoseVector,
    val rotation: PoseQuaternion,
    val traveledDistanceMeters: Double,
    val traveledRotationDegrees: Double,
)

data class PoseLoopMatch(
    val currentTimestampMs: Long,
    val previousTimestampMs: Long,
    val positionErrorMeters: Double,
    val rotationErrorDegrees: Double,
    val traveledRotationDegrees: Double,
)

/**
 * Lightweight IMU-only pose loop detector.
 *
 * The world frame is fixed at the first 25 IMU samples. Gravity is estimated
 * from that calibration window; subsequent accelerations are rotated into the
 * world frame and integrated without drift correction by design.
 */
class PoseLoopDetector(
    private val calibrationSampleCount: Int = 25,
    private val positionThresholdMeters: Double = 0.75,
    private val rotationThresholdDegrees: Double = 25.0,
    private val minimumLoopAgeMs: Long = 3_000L,
    private val minimumTravelMeters: Double = 1.0,
    private val minimumTravelRotationDegrees: Double = 120.0,
) {
    private val calibrationGravity = mutableListOf<PoseVector>()
    private val frameHistory = mutableListOf<FramePose>()
    private val imuPoseHistory = mutableListOf<FramePose>()
    private var lastSample: ImuSample? = null
    private var gravityWorld = PoseVector(0.0, 0.0, 9.81)
    private var rotation = PoseQuaternion(1.0, 0.0, 0.0, 0.0)
    private var position = PoseVector(0.0, 0.0, 0.0)
    private var velocity = PoseVector(0.0, 0.0, 0.0)
    private var traveledDistanceMeters = 0.0
    private var traveledRotationDegrees = 0.0
    private var loopReported = false

    @Synchronized
    fun updateImu(sample: ImuSample) {
        if (calibrationGravity.size < calibrationSampleCount) {
            calibrationGravity += PoseVector(sample.ax.toDouble(), sample.ay.toDouble(), sample.az.toDouble())
            gravityWorld = calibrationGravity.reduce { a, b -> a + b } * (1.0 / calibrationGravity.size)
            lastSample = sample
            return
        }

        val previous = lastSample
        lastSample = sample
        if (previous == null) return

        val dt = ((sample.timestampMs - previous.timestampMs).toDouble() / 1_000.0)
        if (dt <= 0.0 || dt > 0.2) return

        val gyro = PoseQuaternion(0.0, sample.gx.toDouble(), sample.gy.toDouble(), sample.gz.toDouble())
        val derivative = rotation * gyro
        rotation = PoseQuaternion(
            rotation.w + derivative.w * 0.5 * dt,
            rotation.x + derivative.x * 0.5 * dt,
            rotation.y + derivative.y * 0.5 * dt,
            rotation.z + derivative.z * 0.5 * dt,
        ).normalized()

        val accelerationWorld = rotation.rotate(
            PoseVector(sample.ax.toDouble(), sample.ay.toDouble(), sample.az.toDouble())
        ) - gravityWorld
        val displacement = velocity * dt + accelerationWorld * (0.5 * dt * dt)
        position += displacement
        velocity += accelerationWorld * dt
        traveledDistanceMeters += displacement.length()
        traveledRotationDegrees += sqrt(
            sample.gx.toDouble() * sample.gx +
                sample.gy.toDouble() * sample.gy +
                sample.gz.toDouble() * sample.gz
        ) * dt * 180.0 / Math.PI

        imuPoseHistory += FramePose(
            frameTimestampMs = sample.timestampMs,
            position = position,
            rotation = rotation,
            traveledDistanceMeters = traveledDistanceMeters,
            traveledRotationDegrees = traveledRotationDegrees,
        )
        if (imuPoseHistory.size > 3_000) imuPoseHistory.removeAt(0)
    }

    @Synchronized
    fun onFrame(frameTimestampMs: Long): PoseLoopMatch? {
        val current = poseAt(frameTimestampMs) ?: return null
        var best: PoseLoopMatch? = null

        val explorationComplete = current.traveledDistanceMeters >= minimumTravelMeters ||
            current.traveledRotationDegrees >= minimumTravelRotationDegrees
        if (explorationComplete) {
            for (candidate in frameHistory) {
                val ageMs = frameTimestampMs - candidate.frameTimestampMs
                if (ageMs < minimumLoopAgeMs) continue

                val positionError = (current.position - candidate.position).length()
                val rotationError = current.rotation.angleTo(candidate.rotation)
                if (positionError <= positionThresholdMeters &&
                    rotationError <= rotationThresholdDegrees
                ) {
                    val match = PoseLoopMatch(
                        currentTimestampMs = frameTimestampMs,
                        previousTimestampMs = candidate.frameTimestampMs,
                        positionErrorMeters = positionError,
                        rotationErrorDegrees = rotationError,
                        traveledRotationDegrees = current.traveledRotationDegrees,
                    )
                    if (best == null || positionError < best!!.positionErrorMeters) best = match
                }
            }
        }

        frameHistory += current
        if (frameHistory.size > 600) frameHistory.removeAt(0)
        if (loopReported) return null
        if (best != null) loopReported = true
        return best
    }

    @Synchronized
    fun reset() {
        calibrationGravity.clear()
        frameHistory.clear()
        imuPoseHistory.clear()
        lastSample = null
        gravityWorld = PoseVector(0.0, 0.0, 9.81)
        rotation = PoseQuaternion(1.0, 0.0, 0.0, 0.0)
        position = PoseVector(0.0, 0.0, 0.0)
        velocity = PoseVector(0.0, 0.0, 0.0)
        traveledDistanceMeters = 0.0
        traveledRotationDegrees = 0.0
        loopReported = false
    }

    private fun poseAt(timestampMs: Long): FramePose? {
        if (calibrationGravity.size < calibrationSampleCount) return null
        val pose = imuPoseHistory.lastOrNull { it.frameTimestampMs <= timestampMs }
            ?: imuPoseHistory.firstOrNull()
            ?: return null
        return pose.copy(frameTimestampMs = timestampMs)
    }
}
