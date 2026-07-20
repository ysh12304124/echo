from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.providers import get_provider_factory
from app.repositories.database import async_session_factory
from app.repositories.memory_repo import MemoryRepository


async def rebuild(dry_run: bool = False) -> tuple[int, int]:
    providers = get_provider_factory()
    embedding = providers.embedding()
    vector_store = providers.vector_store()
    rebuilt = 0
    skipped = 0

    async with async_session_factory() as db:
        repo = MemoryRepository(db)
        for evidence in await repo.list_all_evidences():
            content = evidence.content.strip()
            memory = await repo.get_time_memory(evidence.memory_id)
            if not content or memory is None:
                skipped += 1
                continue
            if not dry_run:
                result = await embedding.embed_document(content)
                await vector_store.upsert(
                    str(evidence.id),
                    result.vector,
                    {
                        "memory_id": str(evidence.memory_id),
                        "partition": memory.partition.value,
                        "type": evidence.type.value,
                    },
                )
            rebuilt += 1
    return rebuilt, skipped


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild Evidence vectors with the configured document embedding task."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Count eligible Evidence rows without writing vectors."
    )
    args = parser.parse_args()
    rebuilt, skipped = asyncio.run(rebuild(dry_run=args.dry_run))
    print(f"rebuilt={rebuilt} skipped={skipped} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
