# src/repositories/address_repository.py

from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import Address, DeliveryZone
from .base_repository import BaseRepository


class DeliveryZoneRepository(BaseRepository[DeliveryZone]):
    def __init__(self, db: AsyncSession):
        super().__init__(DeliveryZone, db)


    async def list_all(self, active_only: bool = True) -> list[DeliveryZone]:
        stmt = select(DeliveryZone).order_by(DeliveryZone.name)
        if active_only:
            stmt = stmt.where(DeliveryZone.is_active.is_(True))
        return list((await self.db.execute(stmt)).scalars().all())


    async def name_taken(self, name: str, exclude_id: int | None = None) -> bool:
        stmt = select(func.count()).select_from(DeliveryZone).where(DeliveryZone.name == name)
        if exclude_id is not None:
            stmt = stmt.where(DeliveryZone.id != exclude_id)
        return (await self.db.execute(stmt)).scalar_one() > 0
