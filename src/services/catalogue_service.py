# src/services/catalogue_service.py

"""
categories, brands and products. Staff/admin write; the customer app reads.
Nothing here is ever hard-deleted: a product that was sold must stay readable on old orders (RESTRICT FKs),
so 'removing' means is_active = False.
"""


from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import AppError, BusinessRuleError, ConflictError, NotFoundError
from src.models import Brand, Category, Inventory, Product
from src.repositories import BrandRepository, CategoryRepository, ProductRepository
from src.schemas import (
    BrandCreate, BrandUpdate, CategoryCreate, CategoryTree, CategoryUpdate, Page, ProductCreate, ProductPublic,
    ProductQuery, ProductStaff, ProductUpdate,
)
from utilities import slugify

from .audit_service import AuditService

# changes to these are audited (money and tax treatment)
_AUDITED_PRODUCT_FIELDS = ("price", "compare_at_price", "cost_price", "tax_class", "is_active")


class CatalogueService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.categories = CategoryRepository(db)
        self.brands = BrandRepository(db)
        self.products = ProductRepository(db)
        self.audit = AuditService(db)


    # categories
    async def category_tree(self, *, active_only: bool = True) -> list[CategoryTree]:
        """
        one flat query, assembled into a nested tree in memory
        """
        rows = await self.categories.list_all(active_only)
        nodes = {c.id: CategoryTree.model_validate(c) for c in rows}

        roots: list[CategoryTree] = []
        for c in rows:
            node = nodes[c.id]
            parent = nodes.get(c.parent_id) if c.parent_id else None
            # a child whose parent is inactive (and therefore missing) is hidden along with it
            if parent is not None:
                parent.children.append(node)
            elif c.parent_id is None:
                roots.append(node)
        return roots


    async def _descendant_ids(self, category_id: int) -> list[int]:
        """the category itself plus everything beneath it (browsing 'Dairy' must include 'Milk')"""
        rows = await self.categories.list_all(active_only=True)
        by_parent: dict[int | None, list[int]] = {}
        for c in rows:
            by_parent.setdefault(c.parent_id, []).append(c.id)

        out, stack = [], [category_id]
        while stack:
            current = stack.pop()
            out.append(current)
            stack.extend(by_parent.get(current, []))
        return out


    async def create_category(self, data: CategoryCreate, actor_id: int) -> Category:
        if data.parent_id is not None:
            parent = await self.categories.get_by_id(data.parent_id)
            if parent is None or not parent.is_active:
                raise NotFoundError("Parent category not found")

        if await self.categories.name_taken(data.parent_id, data.name):
            raise ConflictError(["name"])

        slug = await self._unique_category_slug(data.name)
        category = Category(**data.model_dump(), slug=slug, created_by=actor_id, updated_by=actor_id)
        self.db.add(category)
        await self._commit(["name or slug"])
        return category


    async def _unique_category_slug(self, name: str) -> str:
        base = slugify(name)
        slug, n = base, 2
        while await self.categories.get_by_slug(slug) is not None:
            slug = f"{base[:115]}-{n}"
            n += 1
        return slug


    async def update_category(self, category_id: int, data: CategoryUpdate, actor_id: int) -> Category:
        category = await self.categories.get_by_id(category_id)
        if category is None:
            raise NotFoundError("Category not found")

        changes = data.model_dump(exclude_unset=True)

        if "parent_id" in changes and changes["parent_id"] is not None:
            await self._check_no_cycle(category_id, changes["parent_id"])

        new_parent = changes.get("parent_id", category.parent_id)
        new_name = changes.get("name", category.name)
        if ("name" in changes or "parent_id" in changes) and await self.categories.name_taken(
            new_parent, new_name, exclude_id=category_id
        ):
            raise ConflictError(["name"])

        if changes.get("is_active") is False and category.is_active:
            if await self.categories.has_active_dependents(category_id):
                raise BusinessRuleError("Deactivate or move this category's active products and sub-categories first")

        for field, value in changes.items():
            setattr(category, field, value)
        category.updated_by = actor_id

        await self._commit(["name or slug"])
        return category


    async def _check_no_cycle(self, category_id: int, new_parent_id: int) -> None:
        """a category cannot be moved under itself or one of its own descendants"""
        if new_parent_id == category_id or new_parent_id in await self._descendant_ids(category_id):
            raise AppError("A category cannot be placed under itself or its own sub-categories")
        if await self.categories.get_by_id(new_parent_id) is None:
            raise NotFoundError("Parent category not found")


    # brands
    async def list_brands(self, *, active_only: bool = True) -> list[Brand]:
        return await self.brands.list_all(active_only)


    async def create_brand(self, data: BrandCreate, actor_id: int) -> Brand:
        slug = slugify(data.name)
        taken = await self.brands.conflicting_fields(name=data.name, slug=slug)
        if taken:
            raise ConflictError(taken)

        brand = Brand(name=data.name, slug=slug, logo_url=data.logo_url, created_by=actor_id, updated_by=actor_id)
        self.db.add(brand)
        await self._commit(["name"])
        return brand


    async def update_brand(self, brand_id: int, data: BrandUpdate, actor_id: int) -> Brand:
        brand = await self.brands.get_by_id(brand_id)
        if brand is None:
            raise NotFoundError("Brand not found")

        changes = data.model_dump(exclude_unset=True)
        if "name" in changes and changes["name"] != brand.name:
            slug = slugify(changes["name"])
            taken = await self.brands.conflicting_fields(name=changes["name"], slug=slug, exclude_id=brand_id)
            if taken:
                raise ConflictError(taken)
            brand.slug = slug

        for field, value in changes.items():
            setattr(brand, field, value)
        brand.updated_by = actor_id

        await self._commit(["name"])
        return brand


    # products: staff writes
    async def create_product(self, data: ProductCreate, actor_id: int) -> ProductStaff:
        await self._check_refs(data.category_id, data.brand_id)

        slug = await self._unique_product_slug(data.name, data.sku)
        taken = await self.products.conflicting_fields(sku=data.sku, barcode=data.barcode, slug=slug)
        if taken:
            raise ConflictError(taken)

        product = Product(**data.model_dump(), slug=slug, created_by=actor_id, updated_by=actor_id)
        # every product gets its (empty) stock row in the same transaction. Stock itself arrives via InventoryService
        product.inventory = Inventory()
        self.db.add(product)
        await self._commit(["sku, barcode or slug"])

        return ProductStaff.from_product(await self.products.get_full(product.id))


    async def _unique_product_slug(self, name: str, sku: str) -> str:
        base = slugify(name, 150)
        if await self.products.conflicting_fields(slug=base):
            return f"{base[:125]}-{slugify(sku, 40)}"
        return base


    async def _check_refs(self, category_id: int | None, brand_id: int | None) -> None:
        if category_id is not None:
            category = await self.categories.get_by_id(category_id)
            if category is None or not category.is_active:
                raise NotFoundError("Category not found")
        if brand_id is not None:
            brand = await self.brands.get_by_id(brand_id)
            if brand is None or not brand.is_active:
                raise NotFoundError("Brand not found")


    async def update_product(self, product_id: int, data: ProductUpdate, actor_id: int) -> ProductStaff:
        product = await self.products.get_by_id(product_id)
        if product is None:
            raise NotFoundError("Product not found")

        changes = data.model_dump(exclude_unset=True)
        await self._check_refs(changes.get("category_id"), changes.get("brand_id"))

        # re-check the cross-field rules against the MERGED values (a PATCH may send only one side of a pair)
        merged = {f: changes.get(f, getattr(product, f)) for f in
                  ("price", "compare_at_price", "min_order_quantity", "max_order_quantity")}
        if merged["compare_at_price"] is not None and merged["compare_at_price"] <= merged["price"]:
            raise AppError("compare_at_price must be greater than price")
        if merged["max_order_quantity"] is not None and merged["max_order_quantity"] < merged["min_order_quantity"]:
            raise AppError("max_order_quantity must be >= min_order_quantity")

        new_slug = None
        if "name" in changes and changes["name"] != product.name:
            new_slug = await self._unique_product_slug(changes["name"], changes.get("sku", product.sku))

        taken = await self.products.conflicting_fields(
            sku=changes.get("sku") if changes.get("sku") != product.sku else None,
            barcode=changes.get("barcode") if changes.get("barcode") != product.barcode else None,
            slug=new_slug if new_slug != product.slug else None,
            exclude_id=product_id,
        )
        if taken:
            raise ConflictError(taken)

        before = {f: getattr(product, f) for f in _AUDITED_PRODUCT_FIELDS if f in changes and changes[f] != getattr(product, f)}

        for field, value in changes.items():
            setattr(product, field, value)
        if new_slug:
            product.slug = new_slug
        product.updated_by = actor_id

        if before:
            self.audit.record(actor_id=actor_id, action="product.updated", entity_type="product", entity_id=product_id,
                              before=before, after={f: changes[f] for f in before})

        await self._commit(["sku, barcode or slug"])
        return ProductStaff.from_product(await self.products.get_full(product_id))


    # products: reads
    async def get_public(self, product_id: int) -> ProductPublic:
        product = await self.products.get_full(product_id)
        if product is None or not product.is_active:
            raise NotFoundError("Product not found")
        return ProductPublic.from_product(product)


    async def get_staff(self, product_id: int) -> ProductStaff:
        product = await self.products.get_full(product_id)
        if product is None:
            raise NotFoundError("Product not found")
        return ProductStaff.from_product(product)


    async def search_public(self, query: ProductQuery) -> Page[ProductPublic]:
        rows, total = await self._search(query, active_only=True)
        return Page.of([ProductPublic.from_product(p) for p in rows], total, query.page, query.per_page)


    async def search_staff(self, query: ProductQuery) -> Page[ProductStaff]:
        rows, total = await self._search(query, active_only=False)
        return Page.of([ProductStaff.from_product(p) for p in rows], total, query.page, query.per_page)


    async def _search(self, query: ProductQuery, *, active_only: bool):
        category_ids = await self._descendant_ids(query.category_id) if query.category_id else None
        return await self.products.search(
            q=query.q, category_ids=category_ids, brand_id=query.brand_id,
            min_price=query.min_price, max_price=query.max_price,
            in_stock_only=query.in_stock_only, active_only=active_only,
            page=query.page, per_page=query.per_page,
        )


    # internals
    async def _commit(self, conflict_fields: list[str]) -> None:
        """commit; a racing duplicate that slipped past the pre-check is caught by the UNIQUE constraint"""
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ConflictError(conflict_fields)
