# src/repositories/customer_repository.py

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Customer
from .base_repository import BaseRepository


class CustomerRepository(BaseRepository[Customer]):
    """Repository for Customer database operations ONLY"""

    def __init__(self, db: AsyncSession):
        """
        constructor
        :param db: AsyncSession
        """
        super().__init__(Customer, db)


    async def get_by_user_id(self, user_id: int, *, with_user: bool = False) -> Optional[Customer]:
        """
        retrieves the customer profile that belongs to a user
        :param user_id: int
        :param with_user: bool
        :return: Customer | None
        """

        stmt = select(Customer).where(Customer.user_id ==  user_id)
        if with_user:
            stmt = stmt.options(selectinload(Customer.user))

        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def get_with_user(self, customer_id: int) -> Optional[Customer]:
        """
        a customer with their User loaded.
        staff screens need the name/phone/email
        :param customer_id: int
        :return: Customer | None
        """

        stmt = (
            select(Customer).where(Customer.id == customer_id)
            .options(selectinload(Customer.user))
            .execution_options(populate_existing=True)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def get_with_addresses(self, customer_id: int) -> Optional[Customer]:
        """
        loads a customer's address book, and the address's delivery zone
        :param customer_id: int
        :return: Customer | None
        """

        stmt = (
            select(Customer)
            .where(Customer.id == customer_id)
            .options(selectinload(Customer.user))
            .execution_options(populate_existing=True)
        )

        return (await self.db.execute(stmt)).scalar_one_or_none()



