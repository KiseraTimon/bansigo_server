# src/repositories/base_repository.py

"""
Repositories are for generic data access.
They only build/execute statements
"""

from typing import TypeVar, Generic, Type, List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import Base


T = TypeVar('T', bound=Base)

class BaseRepository(Generic[T]):
    """Base repository with common CRUD operations"""

    def __init__(self, model: Type[T], db: AsyncSession):
        self.model = model
        self.db = db

    async def get_by_id(self, id: int) -> Optional[T]:
        """
        get a single record by id
        :param id: int
        :return: TypeVar | Any | None
        """

        return await self.db.get(self.model, id)
