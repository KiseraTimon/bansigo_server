# src/repositories/customer_repository.py

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from models import User
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


    async def get_for_update(self, customer_id: int) -> Optional[Customer]:
        """
        this is a row-locked fetch.
        I am implementing this to use before changing loyalty_points from a
            read-modify-write path
        :param customer_id: int
        :return: Customer | None
        """

        stmt = (
            select(Customer)
            .where(Customer.id == customer_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def get_by_phone(self, phone: str) -> Optional[Customer]:
        """
        finds a customer by the user phone number.
        Expects a normalized +2547xxxxxxxx number format
        :param phone: str
        :return: Customer | None
        """

        stmt = (
            select(Customer)
            .join(User, User.id == Customer.user_id)
            .where(User.phone == phone, User.deleted_at.is_(None))
            .options(selectinload(Customer.user))
        )

        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def get_by_email(self, email: str) -> Optional[Customer]:
        """
        finds a customer by the user email
        :param email: str
        :return: Customer | None
        """

        stmt = (
            select(Customer)
            .join(User, User.id == Customer.user_id)
            .where(User.email ==  email, User.deleted_at.is_(None))
            .options(selectinload(Customer.user))
        )

        return (await self.db.execute(stmt)).scalar_one_or_none()



