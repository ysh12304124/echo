package com.echo.phone.domain

import com.echo.phone.data.api.ConversationHighlightDto
import com.echo.phone.data.api.EvidenceEntryDto
import com.echo.phone.data.api.NavigationSummaryDto
import com.echo.phone.data.api.ParticipantDto
import com.echo.phone.data.api.TimeMemoryDetailDto
import com.echo.phone.data.api.TranscriptSegmentDto
import com.echo.phone.data.api.toDomain
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MemoryPresentationTest {
    @Test
    fun generatedTitleUsesSceneNameAndOverviewFallsBackToIdentifyBrief() {
        val presentation = MemorySummary(
            memoryId = "m1",
            memoryType = MemoryType.TIME,
            status = MemoryStatus.COMPLETED,
            title = "MEETING 记录",
            identifyBrief = "讨论了 Echo 的查询体验",
            scene = TimeScene.MEETING,
        ).toPresentation()

        assertEquals("会议记忆", presentation.title)
        assertEquals("讨论了 Echo 的查询体验", presentation.overview)
    }

    @Test
    fun presentationMetadataIsCompactAndDoesNotRequireMedia() {
        val presentation = MemorySummary(
            memoryId = "m1",
            memoryType = MemoryType.TIME,
            status = MemoryStatus.PROCESSING,
            title = "现场检查",
            scene = TimeScene.ONSITE,
            startedAt = "2026-07-20T14:30:00+08:00",
            durationSeconds = 125,
        ).toPresentation()

        assertEquals("现场检查", presentation.title)
        assertEquals("现场拜访 · 2026-07-20 14:30 · 2分05秒 · 处理中", presentation.metadata)
        assertTrue(presentation.overview.isEmpty())
    }

    @Test
    fun meetingDetailMapsPeopleEmotionsAndTranscriptFromApi() {
        val detail = TimeMemoryDetailDto(
            memory_id = "m1",
            title = "",
            scene = "meeting",
            partition = "work",
            status = "completed",
            identify_brief = "",
            navigation_summary = null,
            evidence_status = "ready",
            is_favorited = false,
            duration_seconds = 90,
            event_overview = "确认了下周的发布安排",
            location = "衡山会议室",
            participants = listOf(ParticipantDto("p1", "李明", "/api/v1/media/p1.jpg", person_id = "person-li-ming")),
            conversation_highlights = listOf(
                ConversationHighlightDto("h1", ParticipantDto("p1", "李明"), "happy", "确认周三发布", 12_000),
            ),
            transcript_segments = listOf(
                TranscriptSegmentDto("s1", ParticipantDto("p1", "李明"), "我确认周三发布。", 12_000),
            ),
        ).toDomain()

        assertEquals("确认了下周的发布安排", detail.eventOverview)
        assertEquals("衡山会议室", detail.location)
        assertEquals("李明", detail.participants.single().name)
        assertEquals("person-li-ming", detail.participants.single().personId)
        assertEquals(EmotionalTone.HAPPY, detail.conversationHighlights.single().emotion)
        assertEquals("我确认周三发布。", detail.transcriptSegments.single().content)
    }

    @Test
    fun existingEvidenceIndexCanDriveMeetingDetailUntilNewBackendFieldsExist() {
        val detail = TimeMemoryDetailDto(
            memory_id = "m2",
            title = "体验评审会",
            scene = "meeting",
            partition = "work",
            status = "completed",
            identify_brief = "确定发布节奏和负责人",
            navigation_summary = NavigationSummaryDto(
                persons = listOf("李明", "周宁"),
                spaces = listOf("衡山会议室"),
                evidence_entries = listOf(
                    EvidenceEntryDto(type = "participant", participant_id = "p1", name = "李明", avatar_url = "/api/v1/media/frames/frame_000103.jpg"),
                    EvidenceEntryDto(type = "conversation_highlight", highlight_id = "h1", participant_id = "p1", name = "李明", emotion = "happy", content = "本周完成体验走查，下周三按计划发布。", timestamp_ms = 85_000),
                    EvidenceEntryDto(type = "transcript", segment_id = "t1", content = "先确认发布范围和时间。", timestamp_ms = 4_000),
                ),
            ),
            evidence_status = "ready",
            is_favorited = false,
            duration_seconds = 90,
        ).toDomain()

        assertEquals("衡山会议室", detail.location)
        assertEquals("李明", detail.participants.single().name)
        assertEquals(EmotionalTone.HAPPY, detail.conversationHighlights.single().emotion)
        assertEquals(null, detail.transcriptSegments.single().participant)
    }
}
