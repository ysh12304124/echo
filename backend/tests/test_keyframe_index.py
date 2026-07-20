from types import SimpleNamespace

import pytest

from app.domain.enums import DataPartition, MemoryStatus, TimeScene
from app.domain.models import TimeMemory
from app.providers.base import EmbeddingResult
from app.providers.mock.providers import LocalBlobStore
from app.services.keyframe_index import build_keyframe_entries, keyframe_blob_key


class FakeVisualEmbedding:
    async def embed_images(self, images):
        return [EmbeddingResult(vector=[1.0, 0.0, 0.0], text="") for _ in images]


@pytest.mark.asyncio
async def test_keyframes_are_converted_to_visual_vector_entries(tmp_path):
    blob = LocalBlobStore(str(tmp_path))
    key = "sessions/session-1/frames/whiteboard.jpg"
    await blob.save(key, b"image-bytes", "image/jpeg")
    memory = TimeMemory(
        title="会议",
        scene=TimeScene.MEETING,
        partition=DataPartition.WORK,
        status=MemoryStatus.COMPLETED,
        key_frames=[
            {
                "media_path": key,
                "description": "白板上的交付计划",
                "timestamp_ms": 12000,
            }
        ],
    )
    providers = SimpleNamespace(
        settings=SimpleNamespace(visual_max_image_bytes=1024),
        blob_store=lambda: blob,
        visual_embedding=lambda: FakeVisualEmbedding(),
    )

    entries, skipped = await build_keyframe_entries([memory], providers)

    assert skipped == 0
    assert len(entries) == 1
    assert entries[0][1] == [1.0, 0.0, 0.0]
    assert entries[0][2]["media_path"] == key
    assert entries[0][2]["content"] == "白板上的交付计划"
    assert entries[0][2]["timestamp_ms"] == 12000


def test_keyframe_blob_key_accepts_absolute_and_media_urls():
    assert keyframe_blob_key("/api/v1/media/sessions/a/frames/b.jpg") == (
        "sessions/a/frames/b.jpg"
    )
    assert keyframe_blob_key("/tmp/data/blobs/sessions/a/frames/b.jpg") == (
        "sessions/a/frames/b.jpg"
    )
