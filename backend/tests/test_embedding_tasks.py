import pytest

from app.providers.local.providers import LocalEmbeddingProvider


class RecordingClient:
    def __init__(self):
        self.inputs: list[list[str]] = []

    async def embeddings(self, model: str, texts: list[str]) -> list[list[float]]:
        self.inputs.append(texts)
        return [[1.0, 0.0] for _ in texts]


@pytest.mark.asyncio
async def test_local_embedding_applies_qwen_query_instruction_only():
    client = RecordingClient()
    provider = LocalEmbeddingProvider(
        client,
        "qwen3-embedding:0.6b-q4_k_m",
        "Retrieve evidence passages that answer the question",
    )

    query = await provider.embed_query("项目什么时候交付？")
    document = await provider.embed_document("项目下周三交付")

    assert client.inputs == [
        ["Instruct: Retrieve evidence passages that answer the question\nQuery: 项目什么时候交付？"],
        ["项目下周三交付"],
    ]
    assert query.text.startswith("Instruct:")
    assert document.text == "项目下周三交付"


@pytest.mark.asyncio
async def test_local_embedding_rejects_unexpected_dimension():
    provider = LocalEmbeddingProvider(
        RecordingClient(),
        "qwen3-embedding:0.6b-q4_k_m",
        expected_dimension=1024,
    )

    with pytest.raises(ValueError, match="dimension mismatch"):
        await provider.embed_document("项目下周三交付")
