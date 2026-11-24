# src/repositories/delivery_repository.py

from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import (
    ApprovalStatus, Delivery, DeliveryOfferAction, DeliveryOfferEvent, DeliveryStatus, Order, Rider, RiderStatus,
)
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
        """the dispatcher's queue, oldest first"""
        stmt = (
            select(Delivery).where(Delivery.status == DeliveryStatus.UNASSIGNED)
            .options(selectinload(Delivery.order))
            .order_by(Delivery.created_at)
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_manual_assignment_queue(self, limit: int = 50) -> list[Delivery]:
        """deliveries awaiting manual operator intervention or flagged overdue"""
        stmt = (
            select(Delivery)
            .where(
                or_(
                    Delivery.status == DeliveryStatus.UNASSIGNED,
                    Delivery.is_overdue.is_(True),
                ),
                Delivery.status.notin_((DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED)),
            )
            .options(selectinload(Delivery.order), selectinload(Delivery.rider))
            .order_by(Delivery.needs_manual_assignment.desc(), Delivery.is_overdue.desc(), Delivery.created_at)
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_for_rider(self, rider_id: int, *, active_only: bool = True, limit: int = 50) -> list[Delivery]:
        stmt = select(Delivery).where(Delivery.rider_id == rider_id).options(selectinload(Delivery.order))
        if active_only:
            stmt = stmt.where(Delivery.status.in_(_ACTIVE))
        stmt = stmt.order_by(Delivery.id.desc()).limit(limit)
        return list((await self.db.execute(stmt)).scalars().all())

    async def count_active_for_rider(self, rider_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Delivery)
            .where(Delivery.rider_id == rider_id, Delivery.status.in_(_ACTIVE))
        )
        return int((await self.db.execute(stmt)).scalar_one() or 0)

    async def active_summary_by_rider(self, rider_ids: list[int]) -> tuple[dict[int, int], dict[int, list[tuple[float, float]]], dict[int, bool]]:
        """
        Returns (active_count_map, active_dropoffs_map, has_departed_map) for the given riders.
        """
        if not rider_ids:
            return {}, {}, {}
        stmt = (
            select(Delivery)
            .where(Delivery.rider_id.in_(rider_ids), Delivery.status.in_(_ACTIVE))
            .options(selectinload(Delivery.order))
        )
        rows = list((await self.db.execute(stmt)).scalars().all())
        counts: dict[int, int] = {rid: 0 for rid in rider_ids}
        dropoffs: dict[int, list[tuple[float, float]]] = {rid: [] for rid in rider_ids}
        departed: dict[int, bool] = {rid: False for rid in rider_ids}
        for d in rows:
            if d.rider_id is None:
                continue
            counts[d.rider_id] = counts.get(d.rider_id, 0) + 1
            if d.status in (DeliveryStatus.PICKED_UP, DeliveryStatus.ARRIVED):
                departed[d.rider_id] = True
            if d.order and d.order.delivery_latitude is not None and d.order.delivery_longitude is not None:
                dropoffs.setdefault(d.rider_id, []).append(
                    (float(d.order.delivery_latitude), float(d.order.delivery_longitude))
                )
        return counts, dropoffs, departed

    async def rejected_rider_ids_for_delivery(self, delivery_id: int) -> set[int]:
        stmt = (
            select(DeliveryOfferEvent.rider_id)
            .where(
                DeliveryOfferEvent.delivery_id == delivery_id,
                DeliveryOfferEvent.action.in_((DeliveryOfferAction.REJECTED, DeliveryOfferAction.EXPIRED)),
            )
            .distinct()
        )
        return set((await self.db.execute(stmt)).scalars().all())

    async def list_expired_offers(self, now: datetime, limit: int = 50) -> list[Delivery]:
        stmt = (
            select(Delivery)
            .where(
                Delivery.status == DeliveryStatus.ASSIGNED,
                Delivery.offer_expires_at.is_not(None),
                Delivery.offer_expires_at <= now,
            )
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_overdue_pickups(self, now: datetime, limit: int = 50) -> list[Delivery]:
        stmt = (
            select(Delivery)
            .where(
                Delivery.status == DeliveryStatus.ACCEPTED,
                Delivery.pickup_due_at.is_not(None),
                Delivery.pickup_due_at <= now,
            )
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_overdue_transit(self, now: datetime, limit: int = 50) -> list[Delivery]:
        stmt = (
            select(Delivery)
            .where(
                Delivery.status.in_((DeliveryStatus.PICKED_UP, DeliveryStatus.ARRIVED)),
                Delivery.delivery_due_at.is_not(None),
                Delivery.delivery_due_at <= now,
            )
            .limit(limit)
        )
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

    async def list_dispatchable(self, now: Optional[datetime] = None, limit: int = 50) -> list[Rider]:
        """
        Eligible riders: approved, online (AVAILABLE or BUSY for batching), and not currently in dispatch cooldown.
        """
        stmt = (
            select(Rider)
            .where(
                Rider.approval_status == ApprovalStatus.APPROVED,
                Rider.status.in_((RiderStatus.AVAILABLE, RiderStatus.BUSY)),
            )
            .options(selectinload(Rider.user))
            .order_by(Rider.status, Rider.last_seen_at.desc())
            .limit(limit)
        )
        if now is not None:
            stmt = stmt.where(
                or_(Rider.dispatch_cooldown_until.is_(None), Rider.dispatch_cooldown_until <= now)
            )
        return list((await self.db.execute(stmt)).scalars().all())

    async def list_by_approval(self, status: ApprovalStatus, page: int = 1, per_page: int = 50) -> tuple[list[Rider], int]:
        base = select(Rider).where(Rider.approval_status == status)
        total = (await self.db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(Rider.id).limit(per_page).offset((page - 1) * per_page)
        return list((await self.db.execute(stmt)).scalars().all()), total
