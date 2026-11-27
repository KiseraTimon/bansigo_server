# src/services/wishlist_service.py

from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import NotFoundError
from src.models import Customer, WishlistItem
from src.repositories import ProductRepository, WishlistRepository
from src.schemas import ProductPublic
from utilities import get_logger

log = get_logger(__name__)


class WishlistService:
    """
    manages persisted customer wishlist items synced across sessions and devices
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.wishlist = WishlistRepository(db)
        self.products = ProductRepository(db)

    async def list_products(self, customer: Customer) -> list[ProductPublic]:
        rows = await self.wishlist.list_for_customer(customer.id)
        return [
            ProductPublic.from_product(row.product)
            for row in rows
            if row.product is not None and row.product.is_active
        ]

    async def add_product(self, customer: Customer, product_id: int) -> list[ProductPublic]:
        product = await self.products.get_by_id(product_id)
        if product is None or not product.is_active:
            raise NotFoundError("Product not found")

        existing = await self.wishlist.get_item(customer.id, product_id)
        if existing is None:
            self.db.add(WishlistItem(customer_id=customer.id, product_id=product_id))
            await self.db.commit()
            log.info("Customer %s added product %s to wishlist", customer.id, product_id)

        return await self.list_products(customer)

    async def remove_product(self, customer: Customer, product_id: int) -> list[ProductPublic]:
        removed = await self.wishlist.remove_item(customer.id, product_id)
        if removed:
            await self.db.commit()
            log.info("Customer %s removed product %s from wishlist", customer.id, product_id)
        return await self.list_products(customer)

    async def sync_products(self, customer: Customer, product_ids: list[int]) -> list[ProductPublic]:
        clean_ids = list(dict.fromkeys(pid for pid in product_ids if pid > 0))
        for pid in clean_ids:
            product = await self.products.get_by_id(pid)
            if product is None or not product.is_active:
                continue
            existing = await self.wishlist.get_item(customer.id, pid)
            if existing is None:
                self.db.add(WishlistItem(customer_id=customer.id, product_id=pid))
        await self.db.commit()
        return await self.list_products(customer)
