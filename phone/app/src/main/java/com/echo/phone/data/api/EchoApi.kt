package com.echo.phone.data.api

import com.echo.phone.domain.*
import com.echo.phone.domain.KeyFrame
import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.Response
import retrofit2.http.*

interface EchoApiService {
    @POST("ingest/sessions")
    suspend fun createSession(@Body request: CreateSessionRequest): IngestSessionDto

    @Multipart
    @POST("ingest/sessions/{sessionId}/video")
    suspend fun uploadVideoChunk(
        @Path("sessionId") sessionId: String,
        @Part file: MultipartBody.Part,
        @Part("index") index: RequestBody,
        @Part("is_last") isLast: RequestBody,
        @Part("filename") filename: RequestBody? = null,
    ): UploadAckDto

    @Multipart
    @POST("ingest/sessions/{sessionId}/video/patch")
    suspend fun patchVideoHeader(
        @Path("sessionId") sessionId: String,
        @Part file: MultipartBody.Part,
        @Part("offset") offset: RequestBody,
    ): UploadAckDto

    @Multipart
    @POST("ingest/sessions/{sessionId}/audio")
    suspend fun uploadAudio(
        @Path("sessionId") sessionId: String,
        @Part file: MultipartBody.Part,
        @Part("timestamp_ms") timestampMs: RequestBody,
    ): UploadAckDto

    @POST("ingest/sessions/{sessionId}/imu")
    suspend fun uploadImuBatch(
        @Path("sessionId") sessionId: String,
        @Body batch: ImuBatchDto,
    ): UploadAckDto

    @POST("ingest/sessions/{sessionId}/complete")
    suspend fun completeSession(@Path("sessionId") sessionId: String): MemorySummaryDto

    @GET("memories")
    suspend fun listMemories(
        @Query("partition") partition: String? = null,
        @Query("status") status: String? = null,
    ): MemoryListDto

    @GET("memories/{memoryId}")
    suspend fun getMemory(@Path("memoryId") memoryId: String): TimeMemoryDetailDto

    @PATCH("memories/{memoryId}")
    suspend fun updateMemory(
        @Path("memoryId") memoryId: String,
        @Body request: UpdateMemoryRequest,
    ): TimeMemoryDetailDto

    @DELETE("memories/{memoryId}")
    suspend fun deleteMemory(@Path("memoryId") memoryId: String): Response<Unit>

    @GET("spaces")
    suspend fun listSpaces(@Query("partition") partition: String? = null): SpaceListDto

    @GET("spaces/{spaceId}")
    suspend fun getSpace(@Path("spaceId") spaceId: String): SpaceMemoryDetailDto

    @PATCH("spaces/{spaceId}")
    suspend fun updateSpace(
        @Path("spaceId") spaceId: String,
        @Body request: UpdateSpaceRequest,
    ): SpaceMemoryDetailDto

    @DELETE("spaces/{spaceId}")
    suspend fun deleteSpace(@Path("spaceId") spaceId: String): Response<Unit>

    @GET("memories/{memoryId}/bindings")
    suspend fun listMemoryBindings(@Path("memoryId") memoryId: String): BindingListDto

    @POST("bindings/{bindingId}/confirm")
    suspend fun confirmBinding(@Path("bindingId") bindingId: String): BindingDto

    @POST("bindings/{bindingId}/reject")
    suspend fun rejectBinding(@Path("bindingId") bindingId: String)

    @POST("query")
    suspend fun query(@Body request: QueryRequest): QueryResponseDto

    @GET("persons")
    suspend fun listPersons(@Query("partition") partition: String? = null): PersonListDto

    @GET("persons/{personId}")
    suspend fun getPerson(@Path("personId") personId: String): PersonDetailDto

    @PATCH("persons/{personId}")
    suspend fun updatePerson(
        @Path("personId") personId: String,
        @Body request: UpdatePersonRequest,
    ): PersonDetailDto

    @POST("persons/{personId}/split")
    suspend fun splitPerson(
        @Path("personId") personId: String,
        @Body request: SplitPersonRequest,
    ): PersonDetailDto

    @DELETE("persons/{personId}")
    suspend fun deletePerson(@Path("personId") personId: String)

    @GET("entities")
    suspend fun listEntities(
        @Query("partition") partition: String? = null,
        @Query("entity_type") entityType: String? = null,
    ): EntityListDto

    @POST("export/query-result")
    suspend fun exportQueryResult(@Body request: ExportQueryRequest): ExportResultDto
}

// --- DTOs ---

data class CreateSessionRequest(
    val memory_type: String,
    val scene: String? = null,
    val partition: String = "work",
    val title: String = "",
)

data class IngestSessionDto(
    val session_id: String,
    val memory_type: String,
    val scene: String?,
    val partition: String,
    val status: String,
)

data class UploadAckDto(val id: String, val accepted: Boolean, val filtered: Boolean)

data class MemorySummaryDto(
    val memory_id: String,
    val memory_type: String,
    val status: String,
    val identify_brief: String = "",
    val title: String = "",
    val scene: String? = null,
    val partition: String? = null,
    val started_at: String? = null,
    val duration_seconds: Int = 0,
    val evidence_status: String = "pending",
    val is_favorited: Boolean = false,
)

data class MemoryListDto(val items: List<MemorySummaryDto>, val total: Int)

data class NavigationSummaryDto(
    val persons: List<String>? = null,
    val topics: List<String>? = null,
    val spaces: List<String>? = null,
    val key_moments: List<KeyMomentDto>? = null,
    val suggested_questions: List<String>? = null,
)

data class KeyMomentDto(val id: String, val label: String, val time_offset_seconds: Int)

data class TimeMemoryDetailDto(
    val memory_id: String,
    val title: String,
    val scene: String,
    val partition: String,
    val status: String,
    val identify_brief: String,
    val navigation_summary: NavigationSummaryDto?,
    val evidence_status: String,
    val is_favorited: Boolean,
    val is_locked: Boolean = false,
    val key_frames: List<KeyFrameDto>? = null,
    val duration_seconds: Int,
    val started_at: String? = null,
)

data class KeyFrameDto(val media_url: String = "", val filename: String = "", val frame_index: Int = 0, val timestamp_ms: Long = 0)

data class SpaceAnchorDto(
    val anchor_id: String,
    val name: String,
    val anchor_type: String,
    val position: Map<String, Double>? = null,
)

data class SpaceMemoryDetailDto(
    val space_id: String,
    val title: String,
    val partition: String,
    val status: String,
    val quality: String?,
    val model_url: String?,
    val model_format: String? = null,
    val identify_brief: String,
    val is_favorited: Boolean,
    val is_locked: Boolean = false,
    val key_frames: List<KeyFrameDto>? = null,
    val anchors: List<SpaceAnchorDto>? = null,
    val captured_at: String? = null,
)

data class SpaceListDto(val items: List<SpaceMemoryDetailDto>, val total: Int)

data class QueryRequest(
    val question: String,
    val scope: String,
    val memory_id: String? = null,
    val space_id: String? = null,
)

data class QueryEvidenceDto(
    val evidence_id: String,
    val type: String,
    val content: String,
    val confidence: String,
    val media_url: String?,
    val timestamp_ms: Long,
)

data class QuerySourceDto(
    val memory_id: String,
    val memory_title: String,
    val scene: String?,
    val time_offset_seconds: Int,
)

data class QueryResponseDto(
    val query_id: String,
    val status: String,
    val answer: String?,
    val evidences: List<QueryEvidenceDto>,
    val sources: List<QuerySourceDto>? = null,
    val uncertainty_reason: String?,
)

data class PersonListDto(val items: List<PersonSummaryDto>, val total: Int)
data class PersonSummaryDto(val person_id: String, val name: String, val role: String, val memory_count: Int)
data class PersonDetailDto(
    val person_id: String,
    val name: String,
    val role: String = "",
    val notes: String = "",
    val related_memories: List<String> = emptyList(),
)
data class UpdatePersonRequest(
    val name: String? = null,
    val role: String? = null,
    val notes: String? = null,
    val merge_with_id: String? = null,
)
data class SplitPersonRequest(val memory_ids: List<String>, val new_name: String = "")

data class UpdateMemoryRequest(
    val title: String? = null,
    val is_favorited: Boolean? = null,
    val is_locked: Boolean? = null,
    val user_note: String? = null,
)

data class UpdateSpaceRequest(val title: String? = null, val is_favorited: Boolean? = null)

data class BindingDto(
    val binding_id: String,
    val binding_type: String,
    val time_memory_id: String?,
    val space_memory_id: String?,
    val confidence: String,
    val user_confirmed: Boolean,
)
data class BindingListDto(val items: List<BindingDto>, val total: Int)

data class EntityDto(
    val entity_id: String,
    val name: String,
    val entity_type: String,
    val confidence: String,
    val memory_count: Int,
)
data class EntityListDto(val items: List<EntityDto>, val total: Int)

data class ImuSampleDto(val ax: Float, val ay: Float, val az: Float, val gx: Float, val gy: Float, val gz: Float, val timestamp_ms: Long)

data class ImuBatchDto(val samples: List<ImuSampleDto>)

data class ExportQueryRequest(val query_id: String)
data class ExportResultDto(val export_id: String, val content: Map<String, Any?>)

// --- Mappers ---

fun MemorySummaryDto.toDomain() = MemorySummary(
    memoryId = memory_id,
    memoryType = MemoryType.valueOf(memory_type.uppercase()),
    status = MemoryStatus.valueOf(status.uppercase()),
    identifyBrief = identify_brief,
    title = title,
    scene = scene?.let { TimeScene.valueOf(it.uppercase()) },
    partition = partition?.let { DataPartition.valueOf(it.uppercase()) },
    startedAt = started_at,
    durationSeconds = duration_seconds,
    evidenceStatus = evidence_status,
    isFavorited = is_favorited,
)

fun TimeMemoryDetailDto.toDomain() = TimeMemoryDetail(
    memoryId = memory_id,
    title = title,
    scene = TimeScene.valueOf(scene.uppercase()),
    partition = DataPartition.valueOf(partition.uppercase()),
    status = MemoryStatus.valueOf(status.uppercase()),
    identifyBrief = identify_brief,
    navigationSummary = navigation_summary?.let {
        NavigationSummary(
            persons = it.persons ?: emptyList(),
            topics = it.topics ?: emptyList(),
            spaces = it.spaces ?: emptyList(),
            keyMoments = it.key_moments?.map { km ->
                KeyMoment(km.id, km.label, km.time_offset_seconds)
            } ?: emptyList(),
            suggestedQuestions = it.suggested_questions ?: emptyList(),
        )
    },
    evidenceStatus = evidence_status,
    isFavorited = is_favorited,
    isLocked = is_locked,
    keyFrames = key_frames?.map { KeyFrame(mediaUrl = it.media_url, filename = it.filename, frameIndex = it.frame_index, timestampMs = it.timestamp_ms) } ?: emptyList(),
    durationSeconds = duration_seconds,
    startedAt = started_at,
)

fun SpaceMemoryDetailDto.toDomain() = SpaceMemoryDetail(
    spaceId = space_id,
    title = title,
    partition = DataPartition.valueOf(partition.uppercase()),
    status = MemoryStatus.valueOf(status.uppercase()),
    quality = quality,
    modelUrl = model_url,
    modelFormat = model_format,
    identifyBrief = identify_brief,
    isFavorited = is_favorited,
    isLocked = is_locked,
    keyFrames = key_frames?.map { KeyFrame(mediaUrl = it.media_url, filename = it.filename, frameIndex = it.frame_index, timestampMs = it.timestamp_ms) } ?: emptyList(),
    anchors = anchors?.map {
        SpaceAnchor(anchorId = it.anchor_id, name = it.name, anchorType = it.anchor_type)
    } ?: emptyList(),
    capturedAt = captured_at,
)

fun QueryResponseDto.toDomain() = QueryResult(
    queryId = query_id,
    status = QueryResultStatus.valueOf(status.uppercase()),
    answer = answer,
    evidences = evidences.map {
        QueryEvidence(
            evidenceId = it.evidence_id,
            type = EvidenceType.valueOf(it.type.uppercase()),
            content = it.content,
            confidence = ConfidenceLevel.valueOf(it.confidence.uppercase()),
            mediaUrl = it.media_url,
            timestampMs = it.timestamp_ms,
        )
    },
    sources = sources?.map {
        QuerySource(
            memoryId = it.memory_id,
            memoryTitle = it.memory_title,
            scene = it.scene?.let { s -> TimeScene.valueOf(s.uppercase()) },
            timeOffsetSeconds = it.time_offset_seconds,
        )
    } ?: emptyList(),
    uncertaintyReason = uncertainty_reason,
)

fun PersonSummaryDto.toDomain() = PersonSummary(
    personId = person_id,
    name = name,
    role = role,
    memoryCount = memory_count,
)

fun PersonDetailDto.toDomain() = PersonDetail(
    personId = person_id,
    name = name,
    role = role,
    notes = notes,
    relatedMemories = related_memories,
)

fun EntityDto.toDomain() = EntitySummary(
    entityId = entity_id,
    name = name,
    entityType = entity_type,
    confidence = ConfidenceLevel.valueOf(confidence.uppercase()),
    memoryCount = memory_count,
)

fun BindingDto.toDomain() = TimeSpaceBinding(
    bindingId = binding_id,
    bindingType = binding_type,
    timeMemoryId = time_memory_id,
    spaceMemoryId = space_memory_id,
    confidence = ConfidenceLevel.valueOf(confidence.uppercase()),
    userConfirmed = user_confirmed,
)
