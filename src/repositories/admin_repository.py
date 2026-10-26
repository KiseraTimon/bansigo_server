# src/repositories/admin_repository.py

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import Admin, AdminLevel
from .base_repository import BaseRepository


class AdminRepository(BaseRepository[Admin]):
    """
    repository for managing administrator records and privileges
    """

    def __init__(self, db: AsyncSession):
        super().__init__(Admin, db)

    async def get_by_user_id(self, user_id: int) -> Optional[Admin]:
        """
        fetches the admin row that belongs to a user
        :param user_id: int
        :return: Admin | None
        """
        stmt = (
            select(Admin)
            .where(Admin.user_id == user_id)
            .options(selectinload(Admin.user))
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_with_user(self, admin_id: int) -> Optional[Admin]:
        """
        fetches an admin with the associated user profile eager loaded
        :param admin_id: int
        :return: Admin | None
        """
        stmt = (
            select(Admin)
            .where(Admin.id == admin_id)
            .options(selectinload(Admin.user))
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_all_with_users(self) -> list[Admin]:
        """
        fetches all administrator records with their user profile loaded
        :return: list[Admin]
        """
        stmt = (
            select(Admin)
            .options(selectinload(Admin.user))
            .order_by(Admin.id)
        )
        return list((await self.db.execute(stmt)).scalars().all())
