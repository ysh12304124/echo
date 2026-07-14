"""本地模型 Provider 实现，基于 OpenAI 兼容接口。

- LocalLLMProvider：文本推理（事件/实体抽取、导航摘要、证据接地问答）
- LocalVLMProvider：多模态视觉（图片摘要 + OCR），同时实现 VisionProvider 与 OCRProvider
- WhisperASRProvider：语音转写（带时间戳分段）
- LocalEmbeddingProvider：文本向量
"""

from __future__ import annotations

from app.providers.base import (
    ASRProvider,
    EmbeddingProvider,
    EmbeddingResult,
    LLMProvider,
    OCRProvider,
    OCRResult,
    TranscriptSegment,
    VisionProvider,
    VisionResult,
)
from app.providers.local.openai_client import (
    OpenAICompatClient,
    encode_image_data_url,
    parse_json_loose,
)

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


class LocalVLMProvider(VisionProvider, OCRProvider):
    def __init__(self, client: OpenAICompatClient, model: str):
        self.client = client
        self.model = model

    async def analyze_frame(self, image_path: str) -> VisionResult:
        data_url = encode_image_data_url(image_path)
        system = (
            "描述这张第一视角画面里对记忆检索有价值的内容(人物、白板/屏幕、设备、物体、场景)。"
            "输出 JSON: {\"summary\": \"一句话描述\", \"is_informative\": true, \"labels\": [\"\"]}。"
            "若画面模糊/无信息/纯背景，is_informative 设为 false。"
        )
        content = await self.client.chat(
            self.model,
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "分析这张画面。"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_loose(content)
        if isinstance(parsed, dict):
            return VisionResult(
                summary=parsed.get("summary", ""),
                is_informative=bool(parsed.get("is_informative", True)),
                labels=parsed.get("labels", []) or [],
            )
        return VisionResult(summary=content.strip()[:200], is_informative=True)

    async def should_keep_frame(self, image_path: str) -> bool:
        
    async def describe_scene(self, image_path: str) -> str:
        """用 VLM 描述场景"""
        prompt = "请用一句简短的中文描述这张照片中的场景，例如'客厅里的沙发和电视'或'办公室里的会议桌'。只返回描述本身，不超过30个字。"
        return await self.summarize("", prompt)

    result = await self.analyze_frame(image_path)
        return result.is_informative

    async def summarize_session(self, transcript: str, image_path: str | None) -> dict:
        """全量转写 + 首帧图片 → 人物数量 / 所在空间 / 语音内容总结。"""
        system = (
            "你是识境 Echo 的记忆助手。根据给定的一段第一视角图片与语音转写，"
            "总结这段记忆。只依据给定内容，不臆测。"
            "输出 JSON: {\"person_count\": 画面中的人物数量(整数), "
            "\"space\": \"所在空间的简短描述\", "
            "\"voice_summary\": \"语音内容的总结\"}。"
        )
        user_content: list[dict] = [
            {"type": "text", "text": f"语音转写:\n{transcript or '(无语音)'}"},
        ]
        if image_path:
            user_content.append(
                {"type": "image_url", "image_url": {"url": encode_image_data_url(image_path)}}
            )
        content = await self.client.chat(
            self.model,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_loose(content)
        if not isinstance(parsed, dict):
            return {"person_count": 0, "space": "", "voice_summary": content.strip()}
        try:
            person_count = int(parsed.get("person_count", 0) or 0)
        except (TypeError, ValueError):
            person_count = 0
        return {
            "person_count": person_count,
            "space": (parsed.get("space") or "").strip(),
            "voice_summary": (parsed.get("voice_summary") or "").strip(),
        }

    async def extract_text(self, image_path: str) -> OCRResult:
        data_url = encode_image_data_url(image_path)
        system = (
            "识别画面中所有清晰可读的文字(铭牌、标签、名片、屏幕、白板、展板等)。"
            "输出 JSON: {\"text\": \"识别到的文字，无则空\", \"confidence\": 0.0-1.0}。"
        )
        content = await self.client.chat(
            self.model,
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "提取文字。"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_loose(content)
        if isinstance(parsed, dict):
            try:
                conf = float(parsed.get("confidence", 0.0))
            except (TypeError, ValueError):
                conf = 0.0
            return OCRResult(text=(parsed.get("text") or "").strip(), confidence=conf)
        return OCRResult(text="", confidence=0.0)


class WhisperASRProvider(ASRProvider):
    def __init__(self, client: OpenAICompatClient, model: str, language: str | None = None):
        self.client = client
        self.model = model
        self.language = language

    async def transcribe(self, audio_path: str) -> list[TranscriptSegment]:
        data = await self.client.transcribe(self.model, audio_path, self.language)
        segments = data.get("segments") or []
        result: list[TranscriptSegment] = []
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            # whisper 的 avg_logprob 越接近 0 越可信；映射到 [0,1] 粗略置信度
            avg_logprob = seg.get("avg_logprob")
            confidence = 1.0
            if isinstance(avg_logprob, (int, float)):
                confidence = max(0.0, min(1.0, 1.0 + avg_logprob / 5.0))
            result.append(
                TranscriptSegment(
                    text=text,
                    start_ms=int((seg.get("start") or 0.0) * 1000),
                    end_ms=int((seg.get("end") or 0.0) * 1000),
                    speaker_id=None,
                    confidence=confidence,
                )
            )
        if not result and data.get("text"):
            result.append(
                TranscriptSegment(
                    text=data["text"].strip(), start_ms=0, end_ms=0, confidence=0.9
                )
            )
        return result


class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self, client: OpenAICompatClient, model: str):
        self.client = client
        self.model = model

    async def embed(self, text: str) -> EmbeddingResult:
        vectors = await self.client.embeddings(self.model, [text])
        return EmbeddingResult(vector=vectors[0], text=text)
