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


    async def conflicting_fields(
            self,
            *,
            username: str | None = None,
            email: str | None = None,
            phone: str | None = None,
            exclude_id: int | None = None,
    ) -> set[str]:
        """
        identifies which attributes are already taken.

        Used by signup (exclude_id = None) and by PATCH (exclude_id = me, such that
        keeping your own email is not a conflict). One query selects only the three
        columns instead of loading whole User objects.
        :param username: str | None
        :param email: str | None
        :param phone: str | None
        :param exclude_id: int | None
        :return: set[str]
        """

        conditions = []
        if username:
            conditions.append(User.username == username)
        if email:
            conditions.append(User.email == email)
        if phone:
            conditions.append(User.phone == phone)

        if not conditions:
            return set()

        stmt = (
            select(User.username, User.email, User.phone)
            .where(or_(*conditions))
        )

        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)

        taken: set[str] = set()
        for row_username, row_email, row_phone in (await self.db.execute(stmt)).all():
            if username and row_username == username:
                taken.add("username")
            if email and row_email == email:
                taken.add("email")
            if phone and row_phone ==  phone:
                taken.add("phone")

        return taken


    async def usernames_with_prefix(self, prefix: str) -> set[str]:
        """
        existing usernames starting with 'prefix'
        :param prefix: str
        :return: set[str]
        """

        stmt = (
            select(User.username)
            .where(User.username.startswith(prefix, autoescape=True))
        )

        return set((await self.db.execute(stmt)).scalars().all())
