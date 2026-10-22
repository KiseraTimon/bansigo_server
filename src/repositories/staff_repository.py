# src/repositories/staff_repository.py

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Staff
from .base_repository import BaseRepository


class StaffRepository(BaseRepository[Staff]):
    def __init__(self, db: AsyncSession):
        super().__init__(Staff, db)

    async def get_by_user_id(self, user_id: int) -> Optional[Staff]:
        """
        the staff profile that belongs to a user
        :param user_id: int
        :return: Staff | None
        """

        return (await self.db.execute(select(Staff).where(Staff.user_id == user_id))).scalar_one_or_none()
