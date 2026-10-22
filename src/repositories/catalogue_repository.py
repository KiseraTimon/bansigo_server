# src/repositories/catalogue_repository.py

from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import Brand, Category, Inventory, Product
from .base_repository import BaseRepository


class CategoryRepository(BaseRepository[Category]):
    def __init__(self, db: AsyncSession):
        """
        constructor
        :param db: AsyncSession
        """

        super().__init__(Category, db)


    async def get_by_slug(self, slug: str) -> Optional[Category]:
        """
        fetches a catalogue entity by its slug value
        :param slug: str
        :return: Category | None
        """

        return (await self.db.execute(select(Category).where(Category.slug == slug))).scalar_one_or_none()


    async def list_all(self, active_only: bool = True) -> list[Category]:
        """
        fetches every category, flat, in display order (the service builds the tree)
        :param active_only: bool
        :return: list[Category]
        """

        stmt = select(Category).order_by(Category.sort_order, Category.name)
        if active_only:
            stmt = stmt.where(Category.is_active.is_(True))

        return list((await self.db.execute(stmt)).scalars().all())


    async def name_taken(self, parent_id: int | None, name: str, exclude_id: int | None = None) -> bool:
        """
        checks for takes names since sibling names are unique
        :param parent_id: int | None
        :param name: str
        :param exclude_id: int | None
        :return: bool
        """

        stmt = select(func.count()).select_from(Category).where(
            Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id,
            func.lower(Category.name) == name.lower(),
        )

        if exclude_id is not None:
            stmt = stmt.where(Category.id != exclude_id)

        return (await self.db.execute(stmt)).scalar_one() > 0


    async def has_active_dependents(self, category_id: int) -> bool:
        """
        checks if a category still has active children or products.
        Blocks deactivation
        :param category_id: int
        :return: bool
        """

        children = select(func.count()).select_from(Category).where(
            Category.parent_id == category_id, Category.is_active.is_(True)
        )

        products = select(func.count()).select_from(Product).where(
            Product.category_id == category_id, Product.is_active.is_(True)
        )

        return ((await self.db.execute(children)).scalar_one() + (await self.db.execute(products)).scalar_one()) > 0
