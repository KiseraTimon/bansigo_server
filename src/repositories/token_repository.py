# src/repositories/token_repository.py

from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import TokenPurpose, VerificationToken
from .base_repository import BaseRepository


class VerificationTokenRepository(BaseRepository[VerificationToken]):
    # constructor
    def __init__(self, db: AsyncSession):
        """
        constructor
        :param db: AsyncSession
        """
        super().__init__(VerificationToken, db)


    async def get(self, user_id: int, purpose: TokenPurpose) -> Optional[VerificationToken]:
        """
        retrieves a verification token for a user
        :param user_id: int
        :param purpose: TokenPurpose
        :return: VerificationToken | None
        """
        stmt = (
            select(VerificationToken)
            .where(VerificationToken.user_id == user_id, VerificationToken.purpose == purpose)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def delete_for(self, user_id: int, purpose: TokenPurpose | None = None) -> None:
        """
        deletes a token associated to some user
        :param user_id: int
        :param purpose: TokenPurpose | None
        :return: None
        """
        stmt = (
            delete(VerificationToken)
            .where(VerificationToken.user_id == user_id)
        )

        if purpose is not None:
            stmt.where(VerificationToken.purpose == purpose)

        await self.db.execute(stmt)
