# src/repositories/inventory_repository.py

from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Inventory, StockMovement
from .base_repository import BaseRepository


class InventoryRepository(BaseRepository[Inventory]):
    """NOTE: Inventory's primary key is product_id (there is no `id`), so get_all()/count() from the base do not apply"""

    def __init__(self, db: AsyncSession):
        super().__init__(Inventory, db)


    async def lock_for_products(self, product_ids: Iterable[int]) -> dict[int, Inventory]:
        """
        SELECT ... FOR UPDATE on the stock rows, always in ascending product_id order so two checkouts that
        share products lock in the same order and cannot deadlock each other
        :param product_ids: Iterable[int]
        :return: dict[product_id, Inventory]
        """

        ids = sorted(set(product_ids))
        if not ids:
            return {}

        stmt = (
            select(Inventory)
            .where(Inventory.product_id.in_(ids))
            .order_by(Inventory.product_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return {row.product_id: row for row in (await self.db.execute(stmt)).scalars().all()}


    async def list_low_stock(self, page: int = 1, per_page: int = 50) -> tuple[list[Inventory], int]:
        """
        products at or below their reorder level
        :param page: int
        :param per_page: int
        :return: tuple[list[Inventory], int]
        """

        base = select(Inventory).where(Inventory.quantity_on_hand <= Inventory.reorder_level)
        total = (await self.db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(Inventory.product_id).limit(per_page).offset((page - 1) * per_page)
        return list((await self.db.execute(stmt)).scalars().all()), total


class StockMovementRepository(BaseRepository[StockMovement]):
    def __init__(self, db: AsyncSession):
        super().__init__(StockMovement, db)


    async def list_for_product(self, product_id: int, page: int = 1, per_page: int = 50) -> tuple[list[StockMovement], int]:
        """

        :param product_id: int
        :param page: int
        :param per_page: int
        :return: tuple[list[StockMovement], int]
        """

        base = select(StockMovement).where(StockMovement.product_id == product_id)
        total = (await self.db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        stmt = base.order_by(StockMovement.id.desc()).limit(per_page).offset((page - 1) * per_page)
        return list((await self.db.execute(stmt)).scalars().all()), total
