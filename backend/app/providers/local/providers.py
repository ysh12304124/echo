"""本地模型 Provider 实现，基于 OpenAI 兼容接口。

- LocalLLMProvider：文本推理（事件/实体抽取、导航摘要、证据接地问答）
- LocalEmbeddingProvider：文本向量

语音转写(ASR)与视觉(VLM/OCR)已迁到 compute/ 算力服务的异步分析管线，
不再需要本地 provider 实现，见 docs/protocols/compute-service.md。
"""

from __future__ import annotations

from app.providers.base import (
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
)
from app.providers.local.openai_client import OpenAICompatClient, parse_json_loose

# 时间记忆各场景的关键瞬间触发类型（对齐产品文档 5.x）
SCENE_EVENT_TYPES = {
    "meeting": [
        "speaker_change", "whiteboard_change", "decision",
        "commitment", "dispute", "manual_mark",
    ],
    "onsite": [
        "space_switch", "text_appear", "device_appear",
        "person_interaction", "business_semantic", "manual_mark",
    ],
    "quality_time": [
        "request_expression", "interest_expression", "work_showcase",
        "user_commitment", "joint_activity", "manual_mark",
    ],
}


class LocalLLMProvider(LLMProvider):
    def __init__(self, client: OpenAICompatClient, model: str):
        self.client = client
        self.model = model

    async def summarize(self, context: str, prompt: str) -> str:
        messages = [
            {"role": "system", "content": "你是识境 Echo 的记忆助手。只依据给定内容回答，简洁不臆测。"},
            {"role": "user", "content": f"{prompt}\n\n内容:\n{context}"},
        ]
        return (await self.client.chat(self.model, messages, temperature=0.3)).strip()

    async def extract_events(self, transcript: str, scene: str) -> list[dict]:
        allowed = SCENE_EVENT_TYPES.get(scene, SCENE_EVENT_TYPES["meeting"])
        system = (
            "你从时间记忆的转写与现场描述中抽取『关键瞬间』，用于组织证据。"
            "不做完整会议纪要。寒暄闲聊不产出关键瞬间。"
            f"事件类型只能取: {', '.join(allowed)}。"
            "为每个关键瞬间单独给出置信度 confidence (high/medium/low)。"
            "只输出 JSON 数组，元素形如 "
            '{"type": "...", "label": "简短描述", "start_ms": 0, "confidence": "high"}。'
            "无关键瞬间则输出 []。"
        )
        content = await self.client.chat(
            self.model,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": f"场景: {scene}\n转写与描述:\n{transcript}"},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_loose(content)
        if isinstance(parsed, dict):
            parsed = parsed.get("events") or parsed.get("items") or []
        return parsed if isinstance(parsed, list) else []

    async def extract_entities(self, transcript: str, scene: str) -> list[dict]:
        system = (
            "从记忆内容中抽取实体，供跨记忆查询使用。"
            "类型 type 只能是 person/project/device/location。"
            "为每个实体给出 confidence (high/medium/low)；无法确认身份时用 low。"
            "只输出 JSON 数组，元素形如 "
            '{"name": "...", "type": "person", "role": "可选", "confidence": "high"}。'
            "无实体输出 []。"
        )
        content = await self.client.chat(
            self.model,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": f"场景: {scene}\n内容:\n{transcript}"},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_loose(content)
        if isinstance(parsed, dict):
            parsed = parsed.get("entities") or parsed.get("items") or []
        return parsed if isinstance(parsed, list) else []

    async def answer_query(self, question: str, evidence_context: str) -> str:
        result = await self.answer_query_structured(question, evidence_context)
        return result.get("answer", "")

    async def answer_query_structured(
        self, question: str, evidence_context: str
    ) -> dict:
        system = (
            "你是识境 Echo 的查询助手。严格遵守证据优先原则:"
            "只能依据提供的证据回答，绝不猜测、不臆造。"
            "若证据不足以支撑确定答案，answer 返回空字符串。"
            "不要使用『可能/大概/我猜/看起来像』这类措辞给出确定答案。"
            "输出 JSON: {\"answer\": \"...\", \"confidence\": \"high|medium|low\"}。"
            "answer 为空时 confidence 用 low。"
        )
        content = await self.client.chat(
            self.model,
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"问题: {question}\n\n可用证据:\n{evidence_context or '(无证据)'}",
                },
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_loose(content)
        if isinstance(parsed, dict):
            return {
                "answer": (parsed.get("answer") or "").strip(),
                "confidence": parsed.get("confidence", "low"),
            }
        return {"answer": "", "confidence": "low"}

    async def build_navigation_summary(self, scene: str, transcript: str) -> dict:
        system = (
            "生成一段记忆的『导航型摘要』——一个可查询目录，帮助用户知道这段记忆里有什么、"
            "可以问什么。不下结论、不做纪要。"
            "输出 JSON: {\"persons\": [], \"topics\": [], "
            "\"key_moments\": [{\"id\":\"\",\"label\":\"\",\"time_offset_seconds\":0}], "
            "\"suggested_questions\": []}。"
        )
        content = await self.client.chat(
            self.model,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": f"场景: {scene}\n内容:\n{transcript}"},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_loose(content)
        return parsed if isinstance(parsed, dict) else {}


class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self, client: OpenAICompatClient, model: str):
        self.client = client
        self.model = model

    async def embed(self, text: str) -> EmbeddingResult:
        vectors = await self.client.embeddings(self.model, [text])
        return EmbeddingResult(vector=vectors[0], text=text)
