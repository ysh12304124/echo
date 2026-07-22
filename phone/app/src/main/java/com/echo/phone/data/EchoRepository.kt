package com.echo.phone.data

import com.echo.phone.BuildConfig
import com.echo.phone.data.api.*
import com.echo.phone.domain.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody

class EchoRepository(private val api: EchoApiService) {

    /** 将后台返回的相对媒体路径（/api/v1/media/...）拼成绝对 URL，供 WebView/图片加载。 */
    fun absoluteMediaUrl(path: String?): String? {
        if (path.isNullOrBlank()) return null
        if (path.startsWith("http")) return path
        val host = BuildConfig.API_BASE_URL.removeSuffix("/api/v1/").removeSuffix("/")
        val normalizedPath = path.removePrefix("/data/blobs/").let { key ->
            if (path.startsWith("/data/blobs/")) "/api/v1/media/$key" else path
        }
        return host + normalizedPath
    }

    suspend fun listMemories(partition: DataPartition? = null): List<MemorySummary> {
        val resp = api.listMemories(partition = partition?.name?.lowercase())
        return resp.items.map { it.toDomain() }
    }

    suspend fun getMemory(memoryId: String): TimeMemoryDetail {
        return api.getMemory(memoryId).toDomain()
    }

    suspend fun listSpaces(): List<SpaceMemoryDetail> {
        return api.listSpaces().items.map { it.toDomain() }
    }

    suspend fun getSpace(spaceId: String): SpaceMemoryDetail {
        return api.getSpace(spaceId).toDomain()
    }

    suspend fun query(question: String, scope: QueryScope, memoryId: String? = null, spaceId: String? = null): QueryResult {
        val resp = api.query(
            QueryRequest(
                question = question,
                scope = scope.name.lowercase(),
                memory_id = memoryId,
                space_id = spaceId,
            )
        )
        return resp.toDomain()
    }

    suspend fun listPersons(partition: DataPartition? = null): List<PersonSummary> {
        return api.listPersons(partition = partition?.name?.lowercase()).items.map { it.toDomain() }
    }

    // --- 边采边传：流式会话 ---

    suspend fun startSession(
        memoryType: MemoryType,
        scene: TimeScene?,
        partition: DataPartition,
        title: String,
    ): String {
        val session = api.createSession(
            CreateSessionRequest(
                memory_type = memoryType.name.lowercase(),
                scene = scene?.name?.lowercase(),
                partition = partition.name.lowercase(),
                title = title,
            )
        )
        return session.session_id
    }

    suspend fun uploadAudio(sessionId: String, audio: MediaAudio) {
        val part = MultipartBody.Part.createFormData(
            "file", "audio.pcm", audio.data.toRequestBody("audio/pcm".toMediaType())
        )
        api.uploadAudio(sessionId, part, audio.timestampMs.toString().toRequestBody())
    }

    /** 视频分片不落地直接转发后台；[isLast]=true 时携带最终 [filename]，[bytes] 可为空。 */
    suspend fun uploadVideoChunk(sessionId: String, index: Int, isLast: Boolean, filename: String?, bytes: ByteArray) {
        val part = MultipartBody.Part.createFormData(
            "file", "chunk.bin", bytes.toRequestBody("application/octet-stream".toMediaType())
        )
        api.uploadVideoChunk(
            sessionId, part,
            index.toString().toRequestBody(),
            isLast.toString().toRequestBody(),
            filename?.toRequestBody(),
        )
    }

    /** 用录制结束后重读的最终文件头部覆盖之前边录边发时发出的旧头部(MediaRecorder stop() 会回改 mdat size 等字段)。 */
    suspend fun patchVideoHeader(sessionId: String, offset: Long, bytes: ByteArray) {
        val part = MultipartBody.Part.createFormData(
            "file", "patch.bin", bytes.toRequestBody("application/octet-stream".toMediaType())
        )
        api.patchVideoHeader(sessionId, part, offset.toString().toRequestBody())
    }

    suspend fun uploadImuBatch(sessionId: String, samples: List<ImuSample>) {
        if (samples.isEmpty()) return
        val dto = com.echo.phone.data.api.ImuBatchDto(
            samples = samples.map { s ->
                com.echo.phone.data.api.ImuSampleDto(
                    ax = s.ax, ay = s.ay, az = s.az,
                    gx = s.gx, gy = s.gy, gz = s.gz,
                    timestamp_ms = s.timestampMs,
                )
            }
        )
        api.uploadImuBatch(sessionId, dto)
    }

    suspend fun completeSession(sessionId: String): MemorySummary =
        api.completeSession(sessionId).toDomain()

    // --- 记忆编辑 ---

    suspend fun toggleFavorite(memoryId: String, favorited: Boolean) {
        api.updateMemory(memoryId, UpdateMemoryRequest(is_favorited = favorited))
    }

    suspend fun toggleLock(memoryId: String, locked: Boolean) {
        api.updateMemory(memoryId, UpdateMemoryRequest(is_locked = locked))
    }

    suspend fun updateNote(memoryId: String, note: String) {
        api.updateMemory(memoryId, UpdateMemoryRequest(user_note = note))
    }

    suspend fun updateTranscriptSpeaker(memoryId: String, segmentId: String, participant: Participant) {
        api.updateTranscriptSpeaker(
            memoryId,
            segmentId,
            UpdateTranscriptSpeakerRequest(participant.participantId, participant.personId),
        )
    }

    suspend fun renameMemoryParticipant(memoryId: String, participant: Participant, name: String) {
        api.renameMemoryParticipant(
            memoryId,
            participant.participantId,
            RenameMemoryParticipantRequest(name, participant.personId),
        )
    }

    suspend fun deleteMemory(memoryId: String) {
        api.deleteMemory(memoryId)
    }

    // --- 空间 ---

    suspend fun listSpaces(partition: DataPartition?): List<SpaceMemoryDetail> =
        api.listSpaces(partition?.name?.lowercase()).items.map { it.toDomain() }

    suspend fun toggleSpaceFavorite(spaceId: String, favorited: Boolean) {
        api.updateSpace(spaceId, UpdateSpaceRequest(is_favorited = favorited))
    }

    suspend fun deleteSpace(spaceId: String) {
        api.deleteSpace(spaceId)
    }

    // --- 时空绑定 ---

    suspend fun listMemoryBindings(memoryId: String): List<TimeSpaceBinding> =
        api.listMemoryBindings(memoryId).items.map { it.toDomain() }

    suspend fun confirmBinding(bindingId: String): TimeSpaceBinding =
        api.confirmBinding(bindingId).toDomain()

    suspend fun rejectBinding(bindingId: String) {
        api.rejectBinding(bindingId)
    }

    // --- 人物 ---

    suspend fun getPerson(personId: String): PersonDetail = api.getPerson(personId).toDomain()

    suspend fun renamePerson(personId: String, name: String): PersonDetail =
        api.updatePerson(personId, UpdatePersonRequest(name = name)).toDomain()

    suspend fun mergePerson(personId: String, targetId: String): PersonDetail =
        api.updatePerson(personId, UpdatePersonRequest(merge_with_id = targetId)).toDomain()

    suspend fun splitPerson(personId: String, memoryIds: List<String>, newName: String): PersonDetail =
        api.splitPerson(personId, SplitPersonRequest(memoryIds, newName)).toDomain()

    suspend fun deletePerson(personId: String) {
        api.deletePerson(personId)
    }

    // --- 实体 ---

    suspend fun listEntities(partition: DataPartition? = null, type: String? = null): List<EntitySummary> =
        api.listEntities(partition?.name?.lowercase(), type).items.map { it.toDomain() }

    suspend fun downloadText(url: String): String {
        val fullUrl = absoluteMediaUrl(url) ?: url
        val client = okhttp3.OkHttpClient()
        val req = okhttp3.Request.Builder().url(fullUrl).build()
        return kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) throw Exception("HTTP ${resp.code}")
                resp.body?.string() ?: throw Exception("Empty body")
            }
        }
    }

    // --- 导出 ---

    suspend fun exportQueryResult(queryId: String): Map<String, Any?> =
        api.exportQueryResult(ExportQueryRequest(queryId)).content
}
