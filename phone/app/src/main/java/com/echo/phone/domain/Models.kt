package com.echo.phone.domain

enum class DataPartition { WORK, QUALITY_TIME }
enum class TimeScene { MEETING, ONSITE, QUALITY_TIME }
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
    val durationSeconds: Int,
)

data class SpaceMemoryDetail(
    val spaceId: String,
    val title: String,
    val partition: DataPartition,
    val status: MemoryStatus,
    val quality: String?,
    val modelUrl: String?,
    val identifyBrief: String,
    val isFavorited: Boolean,
    val anchors: List<SpaceAnchor> = emptyList(),
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

/**
 * 眼镜物理按键动作（由眼镜端 CXR-S App 经 rk_custom_key 上报）。
 * 手机端据自身录制状态映射为开始/停止/标记等语义。
 */
enum class GlassKeyAction {
    /** 触控板单指单击（镜腿按键，系统保留用于进/出 App，应用层不依赖） */
    CLICK,
    /** 触控板单指双击（系统保留用于退出 App） */
    DOUBLE_CLICK,
    LONG_PRESS,
    SWIPE_FORWARD,
    SWIPE_BACK,
    /** 触控板双指单击 —— 开始/停止录制 */
    TWO_FINGER_SINGLE_TAP,
    /** 触控板双指双击 —— 暂停/恢复 */
    TWO_FINGER_DOUBLE_TAP,
    /** 触控板双指前滑 —— 标记瞬间 */
    TWO_FINGER_SWIPE_FORWARD,
    OTHER,
}
