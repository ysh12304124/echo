package com.echo.phone.domain

enum class DataPartition { WORK, QUALITY_TIME }
enum class TimeScene { MEETING, ONSITE, QUALITY_TIME }
enum class MemoryType { TIME, SPACE }

/** 空间记忆场景类型：决定 PointCloudViewer 的默认模式（LARGE→路径浏览，OBJECT→物体环绕）。 */
enum class SpaceSceneType { LARGE, OBJECT }

enum class MemoryStatus {
    NOT_STARTED, RECORDING, PAUSED, UPLOADING, PROCESSING, COMPLETED, FAILED
}
enum class QueryScope { GLOBAL_WORK, MEMORY, SPACE }
enum class QueryResultStatus { CONFIRMED, POSSIBLE, NOT_FOUND }
enum class EvidenceType { VISUAL, TRANSCRIPT, OCR, SPATIAL, USER_NOTE }
enum class ConfidenceLevel { HIGH, MEDIUM, LOW }
enum class GlassesConnectionState { DISCONNECTED, CONNECTING, CONNECTED, RECORDING }
enum class EmotionalTone { HAPPY, ANGRY, SAD, EXCITED, NEUTRAL }

data class Participant(
    val participantId: String,
    val name: String,
    val avatarUrl: String? = null,
    /** 后端人物库匹配成功时提供；用于让跨记忆的人名保持一致。 */
    val personId: String? = null,
)

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
    val eventOverview: String = "",
    val location: String = "",
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
    val eventOverview: String = "",
    val location: String = "",
    val participants: List<Participant> = emptyList(),
    val conversationHighlights: List<ConversationHighlight> = emptyList(),
    val transcriptSegments: List<TranscriptSegment> = emptyList(),
)

data class ConversationHighlight(
    val highlightId: String,
    val participant: Participant?,
    val emotion: EmotionalTone = EmotionalTone.NEUTRAL,
    val content: String,
    val timestampMs: Long = 0,
)

data class TranscriptSegment(
    val segmentId: String,
    val participant: Participant?,
    val content: String,
    val timestampMs: Long,
)

data class CameraPose(
    val position: FloatArray,
    val rotation: FloatArray,
    val forward: FloatArray,
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is CameraPose) return false
        return position.contentEquals(other.position) &&
            rotation.contentEquals(other.rotation) &&
            forward.contentEquals(other.forward)
    }
    override fun hashCode(): Int = position.contentHashCode() * 31 + rotation.contentHashCode()
}

data class OrbitCircle(
    val center: FloatArray,
    val radius: Float,
    val normal: FloatArray,
) {
    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is OrbitCircle) return false
        return center.contentEquals(other.center) && radius == other.radius && normal.contentEquals(other.normal)
    }
    override fun hashCode(): Int = center.contentHashCode() * 31 + radius.hashCode()
}

data class AnchorPoint(val x: Float, val y: Float, val z: Float, val method: String = "")

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
    val sceneType: String? = null,
    val posesUrl: String? = null,
    val anchorPoint: AnchorPoint? = null,
    val recordingDurationSec: Float = 0f,
    val sceneSummary: String = "",
    val loopAngle: Float? = null,
)

data class QueryEvidence(
    val evidenceId: String,
    val type: EvidenceType,
    val content: String,
    val confidence: ConfidenceLevel,
    val sourceConfidence: ConfidenceLevel? = null,
    val retrievalScore: Double? = null,
    val usedInAnswer: Boolean = false,
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

data class VoiceQueryResult(
    val transcript: String,
    val durationMs: Int = 0,
    val asrAvgLogprob: Double?,
    val asrAccepted: Boolean,
    val rejectionReason: String?,
    val result: QueryResult?,
)

data class VoiceTranscriptionResult(
    val transcript: String,
    val durationMs: Int,
    val asrAvgLogprob: Double?,
    val asrAccepted: Boolean,
    val rejectionReason: String?,
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

data class VoiceQueryResult(
    val transcript: String,
    val durationMs: Int = 0,
    val asrAvgLogprob: Double?,
    val asrAccepted: Boolean,
    val rejectionReason: String?,
    val result: QueryResult?,
)

data class VoiceTranscriptionResult(
    val transcript: String,
    val durationMs: Int,
    val asrAvgLogprob: Double?,
    val asrAccepted: Boolean,
    val rejectionReason: String?,
)

data class SpaceAnchor(
    val anchorId: String,
    val name: String,
    val anchorType: String,
    val position: AnchorPoint? = null,
)

data class DeviceStatus(
    val connected: Boolean,
    val batteryPercent: Int = 0,
    val isRecordingTime: Boolean = false,
    val isRecordingSpace: Boolean = false,
    val recordingDurationMs: Long = 0,
)

data class MediaAudio(val data: ByteArray, val timestampMs: Long)

/** 眼镜端边录边发的视频分片(不落地,直接转发后台)。 */
sealed class VideoChunk {
    /** [streamId] 对应眼镜端本地生成的记忆会话 sid,[index] 单调递增。 */
    data class Data(val streamId: String, val index: Int, val bytes: ByteArray) : VideoChunk()
    /**
     * 覆盖写文件头部 [offset] 起的 [bytes]。MediaRecorder 在 stop() 时会回改 mdat box 的
     * 64bit size 字段(已流式发出的旧值已过期)，需要用录制结束后重读的正确头部覆盖它。
     * 必须在 [End] 之前送达，backend 才能在 rename 前完成覆盖。
     */
    data class Patch(val streamId: String, val offset: Long, val bytes: ByteArray) : VideoChunk()
    /** 视频录制结束,[filename] = 场景_开始时间_结束时间.mp4。 */
    data class End(val streamId: String, val filename: String) : VideoChunk()
}

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
 * [glassSid] 为眼镜端本地生成的记忆会话 id，用于与其后续 video_chunk/video_end 分片对账。
 */
data class GlassCommand(
    val type: GlassCommandType,
    val scene: TimeScene? = null,
    val glassSid: String? = null,
)


data class KeyFrame(val mediaUrl: String = "", val filename: String = "", val frameIndex: Int = 0, val timestampMs: Long = 0)
