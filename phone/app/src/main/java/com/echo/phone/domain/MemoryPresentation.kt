package com.echo.phone.domain

data class MemoryPresentation(
    val title: String,
    val overview: String,
    val metadata: String,
    val clues: List<String> = emptyList(),
)

fun MemorySummary.toPresentation(): MemoryPresentation = MemoryPresentation(
    title = displayTitle(title, scene, memoryType),
    overview = eventOverview.ifBlank { identifyBrief },
    metadata = listOfNotNull(
        scene?.displayName(),
        startedAt.displayTime(),
        durationSeconds.takeIf { it > 0 }?.formatDuration(),
        status.displayName(),
    ).joinToString(" · "),
)

fun TimeMemoryDetail.toPresentation(): MemoryPresentation = MemoryPresentation(
    title = displayTitle(title, scene, MemoryType.TIME),
    overview = eventOverview.ifBlank { identifyBrief },
    metadata = listOfNotNull(
        scene.displayName(),
        startedAt.displayTime(),
        durationSeconds.takeIf { it > 0 }?.formatDuration(),
        status.displayName(),
    ).joinToString(" · "),
    clues = buildList {
        addAll(navigationSummary?.persons.orEmpty())
        addAll(navigationSummary?.topics.orEmpty())
        addAll(navigationSummary?.spaces.orEmpty())
    }.distinct().take(6),
)

fun TimeMemoryDetail.displayParticipants(): List<Participant> =
    if (participants.isNotEmpty()) participants
    else navigationSummary?.persons.orEmpty().map { name ->
        Participant(participantId = name, name = name)
    }

fun TimeScene.displayName(): String = when (this) {
    TimeScene.MEETING -> "会议"
    TimeScene.ONSITE -> "现场拜访"
    TimeScene.QUALITY_TIME -> "陪伴"
}

fun MemoryStatus.displayName(): String = when (this) {
    MemoryStatus.NOT_STARTED -> "未开始"
    MemoryStatus.RECORDING -> "记录中"
    MemoryStatus.PAUSED -> "已暂停"
    MemoryStatus.UPLOADING -> "上传中"
    MemoryStatus.PROCESSING -> "处理中"
    MemoryStatus.COMPLETED -> "已完成"
    MemoryStatus.FAILED -> "处理失败"
}

fun Long.formatTimestamp(): String {
    val totalSeconds = this / 1_000
    val hours = totalSeconds / 3_600
    val minutes = (totalSeconds % 3_600) / 60
    val seconds = totalSeconds % 60
    return if (hours > 0) "%02d:%02d:%02d".format(hours, minutes, seconds)
    else "%02d:%02d".format(minutes, seconds)
}

private fun Int.formatDuration(): String {
    val minutes = this / 60
    val seconds = this % 60
    return when {
        minutes == 0 -> "${seconds}秒"
        seconds == 0 -> "${minutes}分钟"
        else -> "${minutes}分%02d秒".format(seconds)
    }
}

private fun String?.displayTime(): String? = this
    ?.takeIf { it.length >= 16 }
    ?.let { "${it.substring(0, 10)} ${it.substring(11, 16)}" }

private fun displayTitle(title: String, scene: TimeScene?, type: MemoryType): String {
    val isGeneratedTitle = title.isBlank() || title.endsWith("记录") || title.equals(scene?.name, ignoreCase = true)
    if (!isGeneratedTitle) return title
    return when (type) {
        MemoryType.SPACE -> "空间记忆"
        MemoryType.TIME -> when (scene) {
            TimeScene.MEETING -> "会议记忆"
            TimeScene.ONSITE -> "现场拜访"
            TimeScene.QUALITY_TIME -> "陪伴时光"
            null -> "时间记忆"
        }
    }
}
