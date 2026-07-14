package com.echo.phone.domain

enum class DataPartition { WORK, QUALITY_TIME }
enum class TimeScene { MEETING, ONSITE, QUALITY_TIME, SPACE }
enum class SpaceType(val label: String) { SINGLE_OBJECT("单物体"), LARGE_SCENE("大场景") }
enum class MemoryType { TIME, SPACE }
enum class MemoryStatus {
    NOT_STARTED, RECORDING, PAUSED, UPLOADING, PROCESSING, COMPLETED, FAILED
}
enum class QueryScope { GLOBAL_WORK, MEMORY, SPACE }
enum class QueryResultStatus { CONFIRMED, POSSIBLE, NOT_FOUND }
enum class EvidenceType { VISUAL, TRANSCRIPT, OCR, SPATIAL, USER_NOTE }
enum class ConfidenceLevel { HIGH, MEDIUM, LOW }
enum class GlassesConnectionState { DISCONNECTED, CONNECTING, CONNECTED, RECORDING }

data class MemorySummary(
    val memoryId: String,
    val memoryType: MemoryType,
    val status: MemoryStatus,
    val identifyBrief: String = "",
    val title: String = "",
    val scene: TimeScene? = null,
    val partition: DataPartition? = null,
    val startedAt: String? = null,
    val durationSeconds: Int = 0,
    val evidenceStatus: String = "pending",
    val isFavorited: Boolean = false,
)

data class NavigationSummary(
    val persons: List<String> = emptyList(),
    val topics: List<String> = emptyList(),
    val spaces: List<String> = emptyList(),
    val keyMoments: List<KeyMoment> = emptyList(),
    val suggestedQuestions: List<String> = emptyList(),
)

data class KeyMoment(val id: String, val label: String, val timeOffsetSeconds: Int)

data class TimeMemoryDetail(
    val memoryId: String,
    val title: String,
    val scene: TimeScene,
    val partition: DataPartition,
    val status: MemoryStatus,
    val identifyBrief: String,
    val navigationSummary: NavigationSummary?,
    val evidenceStatus: String,
    val isFavorited: Boolean,
    val isLocked: Boolean = false,
    val keyFrames: List<KeyFrame> = emptyList(),
    val durationSeconds: Int,
    val startedAt: String? = null,
)

data class SpaceMemoryDetail(
    val spaceId: String,
    val title: String,
    val partition: DataPartition,
    val status: MemoryStatus,
    val quality: String?,
    val modelUrl: String?,
    val modelFormat: String? = null,
    val identifyBrief: String,
    val isFavorited: Boolean,
    val isLocked: Boolean = false,
    val keyFrames: List<KeyFrame> = emptyList(),
    val anchors: List<SpaceAnchor> = emptyList(),
    val capturedAt: String? = null,
)

data class QueryEvidence(
    val evidenceId: String,
    val type: EvidenceType,
    val content: String,
    val confidence: ConfidenceLevel,
    val mediaUrl: String?,
    val timestampMs: Long,
)

data class QueryResult(
    val queryId: String,
    val status: QueryResultStatus,
    val answer: String?,
    val evidences: List<QueryEvidence>,
    val sources: List<QuerySource> = emptyList(),
    val uncertaintyReason: String?,
)

data class PersonSummary(
    val personId: String,
    val name: String,
    val role: String,
    val memoryCount: Int,
)

data class PersonDetail(
    val personId: String,
    val name: String,
    val role: String = "",
    val notes: String = "",
    val relatedMemories: List<String> = emptyList(),
)

data class EntitySummary(
    val entityId: String,
    val name: String,
    val entityType: String,
    val confidence: ConfidenceLevel,
    val memoryCount: Int,
)

data class TimeSpaceBinding(
    val bindingId: String,
    val bindingType: String,
    val timeMemoryId: String?,
    val spaceMemoryId: String?,
    val confidence: ConfidenceLevel,
    val userConfirmed: Boolean,
)

data class QuerySource(
    val memoryId: String,
    val memoryTitle: String,
    val scene: TimeScene?,
    val timeOffsetSeconds: Int,
)

data class SpaceAnchor(
    val anchorId: String,
    val name: String,
    val anchorType: String,
)

data class DeviceStatus(
    val connected: Boolean,
    val batteryPercent: Int = 0,
    val isRecordingTime: Boolean = false,
    val isRecordingSpace: Boolean = false,
    val recordingDurationMs: Long = 0,
)

data class MediaFrame(val data: ByteArray, val timestampMs: Long, val isKeyMoment: Boolean = false)
data class MediaAudio(val data: ByteArray, val timestampMs: Long)

data class ImuSample(
    val ax: Float, val ay: Float, val az: Float,
    val gx: Float, val gy: Float, val gz: Float,
    val timestampMs: Long,
)

/** 眼镜端下发的记忆控制指令类型。 */
enum class GlassCommandType { START, STOP }

/**
 * 眼镜端记忆控制指令（由眼镜 CXR-S App 经 rk_custom_key 上报）。
 *
 * 记忆的开始/结束完全由眼镜端主导：用户在眼镜内选择场景后启动 [START]（携带 [scene]），
 * 再次点击则 [STOP]。手机端仅据此驱动录制与上传，不再提供开始入口。
 */
data class GlassCommand(
    val type: GlassCommandType,
    val scene: TimeScene? = null,
)


data class KeyFrame(val mediaUrl: String = "", val filename: String = "", val frameIndex: Int = 0, val timestampMs: Long = 0)
