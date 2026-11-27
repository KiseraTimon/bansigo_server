# src/repositories/wishlist_repository.py

from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import Product, WishlistItem
from .base_repository import BaseRepository


class WishlistRepository(BaseRepository[WishlistItem]):
    """
    repository for customer wishlist persistence
    """

    def __init__(self, db: AsyncSession):
        super().__init__(WishlistItem, db)

    async def list_for_customer(self, customer_id: int) -> list[WishlistItem]:
        stmt = (
            select(WishlistItem)
            .where(WishlistItem.customer_id == customer_id)
            .options(
                selectinload(WishlistItem.product).selectinload(Product.brand),
                selectinload(WishlistItem.product).selectinload(Product.inventory),
                selectinload(WishlistItem.product).selectinload(Product.category),
            )
            .order_by(WishlistItem.id.desc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_item(self, customer_id: int, product_id: int) -> Optional[WishlistItem]:
        stmt = select(WishlistItem).where(
            WishlistItem.customer_id == customer_id,
            WishlistItem.product_id == product_id,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def remove_item(self, customer_id: int, product_id: int) -> int:
        stmt = delete(WishlistItem).where(
            WishlistItem.customer_id == customer_id,
            WishlistItem.product_id == product_id,
        )
        res = await self.db.execute(stmt)
        return int(res.rowcount or 0)
