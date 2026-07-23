from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.domain.models import TimeMemory
from app.providers import ProviderFactory


def keyframe_blob_key(media_path: str) -> str:
    value = media_path.strip()
    if value.startswith("/api/v1/media/"):
        return value.removeprefix("/api/v1/media/")
    if "/blobs/" in value:
        return value.split("/blobs/", 1)[1]
    return value.lstrip("/")


async def build_keyframe_entries(
    memories: list[TimeMemory], providers: ProviderFactory
) -> tuple[list[tuple[str, list[float], dict]], int]:
    settings = providers.settings
    blob = providers.blob_store()
    pending: list[tuple[str, bytes, dict]] = []
    skipped = 0
    for memory in memories:
        for index, frame in enumerate(memory.key_frames):
            raw_path = str(frame.get("media_path") or frame.get("media_url") or "")
            key = keyframe_blob_key(raw_path)
            path = await blob.get_path(key) if key else None
            if not path:
                skipped += 1
                continue
            data = Path(path).read_bytes()
            if not data or len(data) > settings.visual_max_image_bytes:
                skipped += 1
                continue
            timestamp_ms = int(frame.get("timestamp_ms") or 0)
            content = str(
                frame.get("description")
                or frame.get("label")
                or f"关键帧 {index + 1}"
            )
            entry_id = str(
                uuid5(NAMESPACE_URL, f"echo:keyframe:{memory.id}:{key}")
            )
            pending.append(
                (
                    entry_id,
                    data,
                    {
                        "memory_id": str(memory.id),
                        "partition": memory.partition.value,
                        "type": "visual",
                        "media_path": key,
                        "content": content,
                        "timestamp_ms": timestamp_ms,
                        "confidence": str(frame.get("confidence") or "high"),
                    },
                )
            )

    entries: list[tuple[str, list[float], dict]] = []
    embedding = providers.visual_embedding()
    for start in range(0, len(pending), 16):
        batch = pending[start : start + 16]
        results = await embedding.embed_images([item[1] for item in batch])
        if len(results) != len(batch):
            raise RuntimeError("Chinese-CLIP returned an invalid image batch")
        entries.extend(
            (entry_id, result.vector, metadata)
            for (entry_id, _data, metadata), result in zip(
                batch, results, strict=True
            )
        )
    return entries, skipped


async def index_memory_keyframes(
    memory: TimeMemory, providers: ProviderFactory
) -> tuple[int, int]:
    entries, skipped = await build_keyframe_entries([memory], providers)
    store = providers.visual_vector_store()
    await store.delete_by_filter({"memory_id": str(memory.id)})
    for entry_id, vector, metadata in entries:
        await store.upsert(entry_id, vector, metadata)
    return len(entries), skipped
