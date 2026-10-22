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


class BrandRepository(BaseRepository[Brand]):
    def __init__(self, db: AsyncSession):
        """
        constructor
        :param db: AsyncSession
        """

        super().__init__(Brand, db)


    async def list_all(self, active_only: bool = True) -> list[Brand]:
        """
        fetches a list of all brands
        :param active_only: bool
        :return: list[Brand]
        """

        stmt = select(Brand).order_by(Brand.name)
        if active_only:
            stmt = stmt.where(Brand.is_active.is_(True))
        return list((await self.db.execute(stmt)).scalars().all())


    async def conflicting_fields(self, *, name: str | None, slug: str | None, exclude_id: int | None = None) -> set[str]:
        """
        checks for conflicting brand fields
        :param name: str | None
        :param slug: str | None
        :param exclude_id: int | None
        :return: set[str]
        """

        conditions = []
        if name:
            conditions.append(Brand.name == name)
        if slug:
            conditions.append(Brand.slug == slug)
        if not conditions:
            return set()

        stmt = select(Brand.name, Brand.slug).where(or_(*conditions))
        if exclude_id is not None:
            stmt = stmt.where(Brand.id != exclude_id)

        taken: set[str] = set()
        for row_name, row_slug in (await self.db.execute(stmt)).all():
            if name and row_name == name:
                taken.add("name")
            if slug and row_slug == slug:
                taken.add("slug")
        return taken


class ProductRepository(BaseRepository[Product]):
    # since every relationship on these models is lazy="raise", anything a schema reads must be loaded explicitly
    _FULL = (
        selectinload(Product.category),
        selectinload(Product.brand),
        selectinload(Product.inventory),
    )

    def __init__(self, db: AsyncSession):
        """
        constructor
        :param db: AsyncSession
        """

        super().__init__(Product, db)


    async def get_full(self, product_id: int) -> Optional[Product]:
        """
        fetches full product details
        :param product_id: int
        :return: Product | None
        """

        stmt = (
            select(Product).where(Product.id == product_id)
            .options(*self._FULL)
            .execution_options(populate_existing=True)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def get_by_slug_full(self, slug: str) -> Optional[Product]:
        """
        uses the slug to fetch full product details
        :param slug: str
        :return: Product | None
        """

        stmt = select(Product).where(Product.slug == slug).options(*self._FULL)
        return (await self.db.execute(stmt)).scalar_one_or_none()


    async def get_many(self, ids: Iterable[int]) -> list[Product]:
        """
        fetches details for many products at once
        :param ids: Iterable[int]
        :return: list[Product]
        """

        ids = list(ids)
        if not ids:
            return []
        return list((await self.db.execute(select(Product).where(Product.id.in_(ids)))).scalars().all())


    async def conflicting_fields(
        self, *, sku: str | None = None, barcode: str | None = None, slug: str | None = None,
        exclude_id: int | None = None,
    ) -> set[str]:
        """
        checks for conflicting product fields
        :param sku: str | None
        :param barcode: str | None
        :param slug: str | None
        :param exclude_id: int | None
        :return: set[str]
        """

        conditions = []
        if sku:
            conditions.append(Product.sku == sku)
        if barcode:
            conditions.append(Product.barcode == barcode)
        if slug:
            conditions.append(Product.slug == slug)
        if not conditions:
            return set()

        stmt = select(Product.sku, Product.barcode, Product.slug).where(or_(*conditions))
        if exclude_id is not None:
            stmt = stmt.where(Product.id != exclude_id)

        taken: set[str] = set()
        for r_sku, r_barcode, r_slug in (await self.db.execute(stmt)).all():
            if sku and r_sku == sku:
                taken.add("sku")
            if barcode and r_barcode == barcode:
                taken.add("barcode")
            if slug and r_slug == slug:
                taken.add("slug")
        return taken


    async def search(
        self,
        *,
        q: str | None = None,
        category_ids: Iterable[int] | None = None,
        brand_id: int | None = None,
        min_price: Decimal | None = None,
        max_price: Decimal | None = None,
        in_stock_only: bool = False,
        active_only: bool = True,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Product], int]:
        """
        fetches a filtered, paginated catalogue listing
        :param q: str | None
        :param category_ids: Iterable[int] | None
        :param brand_id: int | None
        :param min_price: Decimal | None
        :param max_price: Decimal | None
        :param in_stock_only: bool
        :param active_only: bool
        :param page: int
        :param per_page: int
        :return: tuple[list[Product], int]
        """

        stmt = select(Product)

        if active_only:
            stmt = stmt.where(Product.is_active.is_(True))
        if q:
            stmt = stmt.where(or_(
                Product.name.icontains(q, autoescape=True),
                Product.sku == q,
                Product.barcode == q,
            ))
        if category_ids is not None:
            stmt = stmt.where(Product.category_id.in_(list(category_ids)))
        if brand_id is not None:
            stmt = stmt.where(Product.brand_id == brand_id)
        if min_price is not None:
            stmt = stmt.where(Product.price >= min_price)
        if max_price is not None:
            stmt = stmt.where(Product.price <= max_price)
        if in_stock_only:
            stmt = stmt.join(Inventory, Inventory.product_id == Product.id).where(
                Inventory.quantity_on_hand - Inventory.quantity_reserved > 0
            )

        total = (await self.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()

        stmt = (
            stmt.options(*self._FULL)
            .order_by(Product.name, Product.id)
            .limit(per_page)
            .offset((page - 1) * per_page)
        )
        return list((await self.db.execute(stmt)).scalars().all()), total
