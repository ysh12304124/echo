import pytest

from app.providers.local.providers import LocalEmbeddingProvider


class RecordingClient:
    def __init__(self):
        self.inputs: list[list[str]] = []

    async def embeddings(self, model: str, texts: list[str]) -> list[list[float]]:
        self.inputs.append(texts)
        return [[1.0, 0.0] for _ in texts]


@pytest.mark.asyncio
async def test_local_embedding_applies_nomic_task_prefixes():
    client = RecordingClient()
    provider = LocalEmbeddingProvider(client, "nomic-embed-text")

    query = await provider.embed_query("项目什么时候交付？")
    document = await provider.embed_document("项目下周三交付")

    assert client.inputs == [
        ["search_query: 项目什么时候交付？"],
        ["search_document: 项目下周三交付"],
    ]
    assert query.text == "search_query: 项目什么时候交付？"
    assert document.text == "search_document: 项目下周三交付"
