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


class AddressRepository(BaseRepository[Address]):
    def __init__(self, db: AsyncSession):
        super().__init__(Address, db)


    async def list_for_customer(self, customer_id: int) -> list[Address]:
        stmt = (
            select(Address).where(Address.customer_id == customer_id)
            .options(selectinload(Address.zone))
            .order_by(Address.is_default.desc(), Address.id)
        )
        return list((await self.db.execute(stmt)).scalars().all())


    async def get_for_customer(self, address_id: int, customer_id: int) -> Optional[Address]:
        """
        owner-scoped lookup
        :param address_id: int
        :param customer_id: int
        :return: Address | None
        """

        stmt = (
            select(Address)
            .where(Address.id == address_id, Address.customer_id == customer_id)
            .options(selectinload(Address.zone))
            .execution_options(populate_existing=True)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def count_for_customer(self, customer_id: int) -> int:
        stmt = select(func.count()).select_from(Address).where(Address.customer_id == customer_id)
        return (await self.db.execute(stmt)).scalar_one()


    async def clear_default(self, customer_id: int, except_id: int | None = None) -> None:
        """
        clears the default location for a customer.
        Each customer has at least one default location
        :param customer_id: int
        :param except_id: int
        :return: None
        """

        stmt = update(Address).where(Address.customer_id == customer_id, Address.is_default.is_(True))
        if except_id is not None:
            stmt = stmt.where(Address.id != except_id)
        await self.db.execute(stmt.values(is_default=False))
