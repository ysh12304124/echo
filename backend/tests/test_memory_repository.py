from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.repositories.database import Base, EvidenceORM, TimeMemoryORM
from app.repositories.memory_repo import MemoryRepository


@pytest.mark.asyncio
async def test_list_all_work_evidences_is_not_limited_by_memory_page_size():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        expected_ids = set()
        for index in range(21):
            memory_id = str(uuid4())
            evidence_id = str(uuid4())
            expected_ids.add(evidence_id)
            session.add(
                TimeMemoryORM(
                    id=memory_id,
                    title=f"work-{index}",
                    scene="meeting",
                    partition="work",
                    status="completed",
                )
            )
            session.add(
                EvidenceORM(
                    id=evidence_id,
                    memory_id=memory_id,
                    type="transcript",
                    content=f"evidence-{index}",
                    confidence="high",
                )
            )

        private_memory_id = str(uuid4())
        session.add(
            TimeMemoryORM(
                id=private_memory_id,
                title="private",
                scene="quality_time",
                partition="quality_time",
                status="completed",
            )
        )
        session.add(
            EvidenceORM(
                id=str(uuid4()),
                memory_id=private_memory_id,
                type="transcript",
                content="private evidence",
                confidence="high",
            )
        )
        await session.commit()

        evidences = await MemoryRepository(session).list_all_work_evidences()

    await engine.dispose()
    assert {str(evidence.id) for evidence in evidences} == expected_ids
