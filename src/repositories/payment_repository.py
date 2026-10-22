# src/repositories/payment_repository.py

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Payment, PaymentEvent, PaymentEventSource, PaymentStatus, Refund, RefundStatus,
)
from .base_repository import BaseRepository

_LIVE_REFUND = (RefundStatus.REQUESTED, RefundStatus.APPROVED, RefundStatus.PROCESSING, RefundStatus.COMPLETED)


class PaymentRepository(BaseRepository[Payment]):
    def __init__(self, db: AsyncSession):
        super().__init__(Payment, db)


    async def get_by_idempotency_key(self, key: str) -> Optional[Payment]:
        return (await self.db.execute(select(Payment).where(Payment.idempotency_key == key))).scalar_one_or_none()


    async def get_by_checkout_id(self, checkout_request_id: str, *, for_update: bool = False) -> Optional[Payment]:
        stmt = select(Payment).where(Payment.provider_checkout_request_id == checkout_request_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def list_for_order(self, order_id: int) -> list[Payment]:
        stmt = select(Payment).where(Payment.order_id == order_id).order_by(Payment.id)
        return list((await self.db.execute(stmt)).scalars().all())


    async def latest_succeeded(self, order_id: int) -> Optional[Payment]:
        stmt = (
            select(Payment)
            .where(Payment.order_id == order_id, Payment.status == PaymentStatus.SUCCEEDED)
            .order_by(Payment.id.desc())
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def list_stale_pending(self, now: datetime, limit: int = 50) -> list[Payment]:
        """
        the sweeper's query (backed by idx_payment_status_expiry): prompts whose window has passed with no answer
        """
        stmt = (
            select(Payment)
            .where(Payment.status.in_((PaymentStatus.INITIATED, PaymentStatus.PENDING)), Payment.expires_at < now)
            .order_by(Payment.expires_at)
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())


class PaymentEventRepository(BaseRepository[PaymentEvent]):
    def __init__(self, db: AsyncSession):
        super().__init__(PaymentEvent, db)


    async def get_by_source_external(self, source: PaymentEventSource, external_id: str) -> Optional[PaymentEvent]:
        stmt = select(PaymentEvent).where(PaymentEvent.source == source, PaymentEvent.external_id == external_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def add_if_new(self, event: PaymentEvent) -> tuple[PaymentEvent, bool]:
        """
        insert-first idempotency: the UNIQUE (source, external_id) pair makes a replayed callback harmless.
        The insert runs in a SAVEPOINT so a duplicate does not poison the surrounding transaction
        :param event: PaymentEvent
        :return: (event, is_new). When is_new is False, `event` is the row stored earlier
        """
        try:
            async with self.db.begin_nested():
                self.db.add(event)
                await self.db.flush()
            return event, True
        except IntegrityError:
            existing = await self.get_by_source_external(event.source, event.external_id)
            if existing is None:
                raise
            return existing, False


    async def list_unprocessed(self, limit: int = 100) -> list[PaymentEvent]:
        """
        callbacks that need a human (unauthenticated, unmatched, or mismatched amount)
        """
        stmt = (
            select(PaymentEvent)
            .where(PaymentEvent.processed_at.is_(None))
            .order_by(PaymentEvent.id)
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())


class RefundRepository(BaseRepository[Refund]):
    def __init__(self, db: AsyncSession):
        super().__init__(Refund, db)


    async def sum_active(self, payment_id: int) -> Decimal:
        """
        money already claimed against a payment (requested, approved, in flight or completed)
        """
        stmt = select(func.coalesce(func.sum(Refund.amount), 0)).where(
            Refund.payment_id == payment_id, Refund.status.in_(_LIVE_REFUND)
        )
        return Decimal((await self.db.execute(stmt)).scalar_one())


    async def get_for_update(self, refund_id: int) -> Optional[Refund]:
        stmt = select(Refund).where(Refund.id == refund_id).with_for_update().execution_options(populate_existing=True)
        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def list_for_payment(self, payment_id: int) -> list[Refund]:
        stmt = select(Refund).where(Refund.payment_id == payment_id).order_by(Refund.id)
        return list((await self.db.execute(stmt)).scalars().all())


    async def list_by_status(self, status: RefundStatus, page: int = 1, per_page: int = 50) -> tuple[list[Refund], int]:
        base = select(Refund).where(Refund.status == status)
        total = (await self.db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(Refund.id).limit(per_page).offset((page - 1) * per_page)
        return list((await self.db.execute(stmt)).scalars().all()), total
