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


    async def get_all(self, page: int = 1, per_page: int = 20) -> List[T]:
        """
        get all records with ordered pagination
        :param page: int
        :param per_page: int
        :return: List[TypeVar] | Any
        """

        stmt = {
            select(self.model)
            .order_by(self.model.id)
            .limit(per_page)
            .offset((page - 1) * per_page)
        }

        return list((await self.db.execute(stmt)).scalars().all())


    async def add(self, instance: T) -> T:
        """
        stages a new row
        :param instance: TypeVar
        :return: TypeVar
        """

        self.db.add(instance)
        await self.db.flush()
        return instance


    async def delete(self, instance: T) -> None:
        """
        deletes a record
        :param instance: Typevar
        :return: None
        """
        await self.db.delete(instance)
        await self.db.flush()
