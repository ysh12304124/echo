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
        return host + path
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

    suspend fun createAndUploadSession(
        memoryType: MemoryType,
        scene: TimeScene?,
        partition: DataPartition,
        title: String,
        frames: List<MediaFrame>,
        audioChunks: List<MediaAudio>,
    ): MemorySummary {
        val session = api.createSession(
            CreateSessionRequest(
                memory_type = memoryType.name.lowercase(),
                scene = scene?.name?.lowercase(),
                partition = partition.name.lowercase(),
                title = title,
            )
        )

        for (frame in frames) {
            val part = MultipartBody.Part.createFormData(
                "file", "frame.jpg",
                frame.data.toRequestBody("image/jpeg".toMediaType())
            )
            api.uploadFrame(
                session.session_id, part,
                frame.timestampMs.toString().toRequestBody(),
                if (frame.isKeyMoment) "true".toRequestBody() else null,
            )
        }

        for (audio in audioChunks) {
            val part = MultipartBody.Part.createFormData(
                "file", "audio.pcm",
                audio.data.toRequestBody("audio/pcm".toMediaType())
            )
            api.uploadAudio(
                session.session_id, part,
                audio.timestampMs.toString().toRequestBody(),
            )
        }

        return api.completeSession(session.session_id).toDomain()
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

    suspend fun uploadFrame(sessionId: String, frame: MediaFrame) {
        val part = MultipartBody.Part.createFormData(
            "file", "frame.jpg", frame.data.toRequestBody("image/jpeg".toMediaType())
        )
        api.uploadFrame(
            sessionId, part,
            frame.timestampMs.toString().toRequestBody(),
            if (frame.isKeyMoment) "true".toRequestBody() else null,
        )
    }

    suspend fun uploadAudio(sessionId: String, audio: MediaAudio) {
        val part = MultipartBody.Part.createFormData(
            "file", "audio.pcm", audio.data.toRequestBody("audio/pcm".toMediaType())
        )
        api.uploadAudio(sessionId, part, audio.timestampMs.toString().toRequestBody())
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

    // --- 导出 ---

    suspend fun exportQueryResult(queryId: String): Map<String, Any?> =
        api.exportQueryResult(ExportQueryRequest(queryId)).content
}
