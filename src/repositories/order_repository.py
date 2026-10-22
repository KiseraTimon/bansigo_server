# src/repositories/order_repository.py

from datetime import datetime
from typing import Optional

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import FulfilmentType, Order, OrderItem, OrderStatus, Product
from .base_repository import BaseRepository


class OrderRepository(BaseRepository[Order]):
    # an order is always read WHOLE: items, timeline, delivery and payments (all lazy="raise" on the model)
    _FULL = (
        selectinload(Order.items),
        selectinload(Order.status_history),
        selectinload(Order.delivery),
        selectinload(Order.payments),
    )

    def __init__(self, db: AsyncSession):
        super().__init__(Order, db)


    async def get_full(self, order_id: int, *, for_update: bool = False) -> Optional[Order]:
        """
        one order with everything loaded
        :param order_id: int
        :param for_update: bool
        :return: Order | None
        """
        stmt = (
            select(Order).where(Order.id == order_id)
            .options(*self._FULL)
            .execution_options(populate_existing=True)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def get_by_number(self, order_number: str) -> Optional[Order]:
        """
        fetches an order by the order number
        :param order_number: str
        :return: Order | None
        """

        stmt = select(Order).where(Order.order_number == order_number).options(*self._FULL)
        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def number_exists(self, order_number: str) -> bool:
        """
        checks if the order number exists
        :param order_number: str
        :return: bool
        """

        stmt = select(func.count()).select_from(Order).where(Order.order_number == order_number)
        return (await self.db.execute(stmt)).scalar_one() > 0


    async def get_by_idempotency(self, customer_id: int, key: str) -> Optional[Order]:
        """
        fetches an order using its idempotency key
        :param customer_id: int
        :param key: str
        :return: Order | None
        """

        stmt = (
            select(Order)
            .where(Order.customer_id == customer_id, Order.idempotency_key == key)
            .options(*self._FULL)
            .execution_options(populate_existing=True)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def list_for_customer(
        self, customer_id: int, *, statuses: list[OrderStatus] | None = None, page: int = 1, per_page: int = 20
    ) -> tuple[list[Order], int]:
        """
        fetches a customer's list of orders
        :param customer_id: int
        :param statuses: list[OrderStatus]
        :param page: int
        :param per_page: int
        :return: tuple[list[Order], int]
        """

        base = select(Order).where(Order.customer_id == customer_id)
        if statuses:
            base = base.where(Order.status.in_(statuses))
        return await self._page(base, page, per_page)


    async def list_for_staff(
        self,
        *,
        status: OrderStatus | None = None,
        fulfilment_type: FulfilmentType | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Order], int]:
        """
        lists orders for the staff
        :param status: OrderStatus | None
        :param fulfilment_type: FulfilmentType | None
        :param page: int
        :param per_page: int
        :return: tuple[list[Order], int]
        """

        base = select(Order)
        if status is not None:
            base = base.where(Order.status == status)
        if fulfilment_type is not None:
            base = base.where(Order.fulfilment_type == fulfilment_type)
        return await self._page(base, page, per_page)


    async def _page(self, base, page: int, per_page: int) -> tuple[list[Order], int]:
        total = (await self.db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(Order.created_at.desc(), Order.id.desc()).limit(per_page).offset((page - 1) * per_page)
        return list((await self.db.execute(stmt)).scalars().all()), total


    async def has_age_restricted_items(self, order_id: int) -> bool:
        """
        verifies if order has age restricted items e.g. alcohol etc.
        :param order_id: int
        :return: bool
        """

        stmt = select(exists().where(
            OrderItem.order_id == order_id,
            OrderItem.product_id == Product.id,
            Product.is_age_restricted.is_(True),
        ))
        return bool((await self.db.execute(stmt)).scalar())


    async def list_stale_unpaid(self, cutoff: datetime, limit: int = 100) -> list[Order]:
        """
        lists orders with pending payments before the cutoff.
        Handles the release of their stock reservations
        :param cutoff: datetime
        :param limit: int
        :return: list[Order]
        """

        stmt = (
            select(Order)
            .where(Order.status == OrderStatus.PENDING_PAYMENT, Order.created_at < cutoff)
            .order_by(Order.created_at)
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())
