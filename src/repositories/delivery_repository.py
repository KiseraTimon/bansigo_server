# src/repositories/delivery_repository.py

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import ApprovalStatus, Delivery, DeliveryStatus, Rider, RiderStatus
from .base_repository import BaseRepository

_ACTIVE = (DeliveryStatus.ASSIGNED, DeliveryStatus.ACCEPTED, DeliveryStatus.PICKED_UP, DeliveryStatus.ARRIVED)


class DeliveryRepository(BaseRepository[Delivery]):
    def __init__(self, db: AsyncSession):
        super().__init__(Delivery, db)


    async def get_for_update(self, delivery_id: int) -> Optional[Delivery]:
        stmt = select(Delivery).where(Delivery.id == delivery_id).with_for_update().execution_options(populate_existing=True)
        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def get_by_order(self, order_id: int) -> Optional[Delivery]:
        return (await self.db.execute(select(Delivery).where(Delivery.order_id == order_id))).scalar_one_or_none()


    async def list_unassigned(self, limit: int = 50) -> list[Delivery]:
        """
        the dispatcher's queue, oldest first
        """
        stmt = (
            select(Delivery).where(Delivery.status == DeliveryStatus.UNASSIGNED)
            .options(selectinload(Delivery.order))
            .order_by(Delivery.created_at)
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())


    async def list_for_rider(self, rider_id: int, *, active_only: bool = True, limit: int = 50) -> list[Delivery]:
        stmt = select(Delivery).where(Delivery.rider_id == rider_id).options(selectinload(Delivery.order))
        if active_only:
            stmt = stmt.where(Delivery.status.in_(_ACTIVE))
        stmt = stmt.order_by(Delivery.id.desc()).limit(limit)
        return list((await self.db.execute(stmt)).scalars().all())
