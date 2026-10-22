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


class RiderRepository(BaseRepository[Rider]):
    def __init__(self, db: AsyncSession):
        super().__init__(Rider, db)


    async def get_by_user_id(self, user_id: int) -> Optional[Rider]:
        return (await self.db.execute(select(Rider).where(Rider.user_id == user_id))).scalar_one_or_none()


    async def get_for_update(self, rider_id: int) -> Optional[Rider]:
        stmt = select(Rider).where(Rider.id == rider_id).with_for_update().execution_options(populate_existing=True)
        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def conflicting_fields(
        self, *, national_id_number: str | None, vehicle_plate: str | None, exclude_id: int | None = None
    ) -> set[str]:
        taken: set[str] = set()
        for field, value in (("national_id_number", national_id_number), ("vehicle_plate", vehicle_plate)):
            if not value:
                continue
            column = getattr(Rider, field)
            stmt = select(func.count()).select_from(Rider).where(column == value)
            if exclude_id is not None:
                stmt = stmt.where(Rider.id != exclude_id)
            if (await self.db.execute(stmt)).scalar_one() > 0:
                taken.add(field)
        return taken


    async def list_dispatchable(self, limit: int = 50) -> list[Rider]:
        """
        the dispatcher's query (backed by idx_rider_dispatch): approved riders who are available
        """
        stmt = (
            select(Rider)
            .where(Rider.approval_status == ApprovalStatus.APPROVED, Rider.status == RiderStatus.AVAILABLE)
            .order_by(Rider.last_seen_at.desc())
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())


    async def list_by_approval(self, status: ApprovalStatus, page: int = 1, per_page: int = 50) -> tuple[list[Rider], int]:
        base = select(Rider).where(Rider.approval_status == status)
        total = (await self.db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(Rider.id).limit(per_page).offset((page - 1) * per_page)
        return list((await self.db.execute(stmt)).scalars().all()), total
