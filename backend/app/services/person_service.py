from __future__ import annotations

from typing import Optional
from uuid import UUID

from app.domain.enums import ConfidenceLevel, DataPartition
from app.domain.models import Person
from app.repositories.memory_repo import MemoryRepository


class PersonService:
    def __init__(self, repo: MemoryRepository):
        self.repo = repo

    async def list_persons(self, partition: DataPartition | None = None) -> list[Person]:
        return await self.repo.list_persons(partition)

    async def get_person(self, person_id: UUID) -> Person | None:
        return await self.repo.get_person(person_id)

    async def update_person(
        self,
        person_id: UUID,
        name: str | None = None,
        role: str | None = None,
        notes: str | None = None,
        merge_with_id: UUID | None = None,
    ) -> Person | None:
        person = await self.repo.get_person(person_id)
        if not person:
            return None

        if merge_with_id:
            target = await self.repo.get_person(merge_with_id)
            if not target:
                return None
            # Must not cross partitions
            if target.partition != person.partition:
                raise ValueError("不能跨数据分区合并人物")

            merged_ids = list(set(target.memory_ids + person.memory_ids))
            await self.repo.update_person(
                merge_with_id,
                memory_ids=merged_ids,
                notes=(target.notes or "") + f"\n合并自: {person.name}",
            )
            await self.repo.delete_person(person_id)
            return await self.repo.get_person(merge_with_id)

        updates = {}
        if name is not None:
            updates["name"] = name
        if role is not None:
            updates["role"] = role
        if notes is not None:
            updates["notes"] = notes
        return await self.repo.update_person(person_id, **updates)

    async def delete_person(self, person_id: UUID) -> bool:
        person = await self.repo.get_person(person_id)
        if not person:
            return False
        await self.repo.delete_person(person_id)
        return True

    async def split_person(
        self, person_id: UUID, memory_ids: list[UUID], new_name: str
    ) -> Person | None:
        """将 person 的部分记忆拆分为一个新人物（纠正误合并）。"""
        person = await self.repo.get_person(person_id)
        if not person:
            return None
        move = [m for m in memory_ids if m in person.memory_ids]
        if not move:
            raise ValueError("待拆分的记忆不属于该人物")
        remaining = [m for m in person.memory_ids if m not in move]
        await self.repo.update_person(person_id, memory_ids=remaining)
        new_person = Person(
            name=new_name or person.name,
            role=person.role,
            partition=person.partition,
            memory_ids=move,
            confidence=ConfidenceLevel.MEDIUM,
        )
        return await self.repo.save_person(new_person)

    async def find_by_name(self, name: str, partition: DataPartition) -> Person | None:
        persons = await self.repo.list_persons(partition)
        for p in persons:
            if p.name == name:
                return p
        return None

    async def ensure_person(
        self,
        name: str,
        partition: DataPartition,
        memory_id: UUID,
        confidence: ConfidenceLevel,
        role: Optional[str] = None,
    ) -> Person:
        existing = await self.find_by_name(name, partition)
        if existing:
            updates = {}
            if memory_id not in existing.memory_ids:
                existing.memory_ids.append(memory_id)
                updates["memory_ids"] = existing.memory_ids
            if role and not existing.role:
                updates["role"] = role
            if updates:
                await self.repo.update_person(existing.id, **updates)
            return existing
        person = Person(
            name=name,
            role=role or "",
            partition=partition,
            memory_ids=[memory_id],
            confidence=confidence,
        )
        return await self.repo.save_person(person)
