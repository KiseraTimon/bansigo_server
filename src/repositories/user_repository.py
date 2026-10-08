# src/repositories/user_repository.py

from typing import Optional

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User
from .base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, db: AsyncSession):
        """
        constructor
        :param db: AsyncSession
        """

        super().__init__(User, db)


    async def find_by_login(self, identifier: str) -> Optional[User]:
        """
        login lookup by email or password.
        :param identifier: str
        :return: User | Any | None
        """

        stmt = (
            select(User)
            .where(or_(User.username == identifier, User.email == identifier))
        )

        return (await self.db.execute(stmt)).scalar_one_or_none()
