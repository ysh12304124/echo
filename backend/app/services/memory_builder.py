from __future__ import annotations

from app.domain.enums import TimeScene
from app.domain.models import NavigationSummary, TimeMemory
from app.providers import ProviderFactory, get_provider_factory


class MemoryBuilder:
    def __init__(self, providers: ProviderFactory | None = None):
        self.providers = providers or get_provider_factory()

    async def build_identify_brief(self, memory: TimeMemory, transcript: str) -> str:
        llm = self.providers.llm()
        context = (
            f"scene={memory.scene.value} partition={memory.partition.value} "
            f"transcript={transcript[:800]}"
        )
        brief = await llm.summarize(context, "用一句话（不超过20字）概括这段记忆是什么，仅作识别用，不下结论")
        return (brief or "").strip() or self._fallback_brief(memory)

    def _fallback_brief(self, memory: TimeMemory) -> str:
        return {
            TimeScene.MEETING: "会议记录",
            TimeScene.ONSITE: "现场拜访",
            TimeScene.QUALITY_TIME: "陪伴时光",
        }.get(memory.scene, "时间记忆记录")

    async def build_navigation_summary(
        self, memory: TimeMemory, transcript: str
    ) -> NavigationSummary:
        llm = self.providers.llm()
        data = await llm.build_navigation_summary(memory.scene.value, transcript)
        if data:
            return NavigationSummary(
                persons=data.get("persons", []) or [],
                topics=data.get("topics", []) or [],
                spaces=data.get("spaces", []) or [],
                key_moments=data.get("key_moments", []) or [],
                evidence_entries=data.get("evidence_entries", []) or [],
                suggested_questions=data.get("suggested_questions", []) or [],
            )
        return self._fallback_navigation(memory, transcript)

    def _fallback_navigation(
        self, memory: TimeMemory, transcript: str
    ) -> NavigationSummary:
        persons: list[str] = []
        topics: list[str] = []
        key_moments: list[dict] = []
        suggested: list[str] = []

        if memory.scene == TimeScene.MEETING:
            topics = ["会议讨论", "决策", "承诺"]
            suggested = ["有没有明确的决策？", "白板上写了什么？", "谁做了承诺？"]
        elif memory.scene == TimeScene.ONSITE:
            topics = ["现场拜访", "设备", "业务信息"]
            suggested = ["现场有哪些设备？", "客户提了哪些需求？"]
        elif memory.scene == TimeScene.QUALITY_TIME:
            topics = ["陪伴时光", "兴趣", "作品"]
            suggested = ["刚才展示了什么？", "我答应过什么？"]

        return NavigationSummary(
            persons=persons,
            topics=topics,
            spaces=[],
            key_moments=key_moments,
            evidence_entries=[],
            suggested_questions=suggested,
        )
