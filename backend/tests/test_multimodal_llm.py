from app.providers.base import ImageInput
from app.providers.local.providers import LocalLLMProvider


class RecordingChatClient:
    def __init__(self):
        self.messages = None

    async def chat(self, model, messages, **_kwargs):
        self.messages = messages
        return '{"answer":"红色","confidence":"high"}'


async def test_multimodal_llm_embeds_local_images_as_data_urls(tmp_path):
    image_path = tmp_path / "frame.png"
    image_path.write_bytes(b"png-bytes")
    client = RecordingChatClient()
    provider = LocalLLMProvider(client, "gemma4:e2b")

    result = await provider.answer_query_multimodal(
        "图片是什么颜色？",
        "[visual] 红色测试图片",
        [ImageInput(path=str(image_path), caption="红色测试图片")],
    )

    assert result == {"answer": "红色", "confidence": "high"}
    content = client.messages[1]["content"]
    assert [item["type"] for item in content] == ["text", "text", "image_url"]
    assert content[-1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "不要生成、猜测或复述任何图片 URL" in client.messages[0]["content"]
