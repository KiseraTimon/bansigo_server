# src/schemas/catalogue.py

from datetime import datetime
from decimal import Decimal
from typing import Annotated, ClassVar, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from src.models import TaxClass, UnitType
from .common import ORMModel
from .types import MoneyAmount, PositiveMoney, Quantity

_Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
_ProductName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
_Sku = Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=40)]
# EAN-8 / UPC-A / EAN-13 / GTIN-14: digits only
_Barcode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{8,14}$")]


class _PatchMixin(BaseModel):
    """PATCH bodies must carry at least one field, and required columns may not be nulled"""
    _NULLABLE: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _validate_patch(self):
        if not self.model_fields_set:
            raise ValueError("no fields provided")
        for field in self.model_fields_set - self._NULLABLE:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


# categories

class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_id: int | None = None
    name: _Name
    description: str | None = None
    image_url: str | None = Field(default=None, max_length=255)
    sort_order: int = 0


class CategoryUpdate(_PatchMixin):
    model_config = ConfigDict(extra="forbid")
    _NULLABLE: ClassVar[frozenset[str]] = frozenset({"description", "image_url"})

    parent_id: int | None = None
    name: _Name | None = None
    description: str | None = None
    image_url: str | None = Field(default=None, max_length=255)
    sort_order: int | None = None
    is_active: bool | None = None


class CategoryPublic(ORMModel):
    id: int
    parent_id: int | None
    name: str
    slug: str
    description: str | None
    image_url: str | None


class CategoryTree(CategoryPublic):
    """a category with its descendants nested (built by the service from one flat query)"""
    children: list["CategoryTree"] = []


# brands

class BrandCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: _Name
    logo_url: str | None = Field(default=None, max_length=255)


class BrandUpdate(_PatchMixin):
    model_config = ConfigDict(extra="forbid")
    _NULLABLE: ClassVar[frozenset[str]] = frozenset({"logo_url"})

    name: _Name | None = None
    logo_url: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class BrandPublic(ORMModel):
    id: int
    name: str
    slug: str
    logo_url: str | None


# products

class _ProductRules(BaseModel):
    """cross-field rules that mirror the products CHECK constraints (friendlier than a database error)"""

    @model_validator(mode="after")
    def _rules(self):
        price = getattr(self, "price", None)
        compare = getattr(self, "compare_at_price", None)
        if price is not None and compare is not None and compare <= price:
            raise ValueError("compare_at_price must be greater than price")

        lo, hi = getattr(self, "min_order_quantity", None), getattr(self, "max_order_quantity", None)
        if lo is not None and hi is not None and hi < lo:
            raise ValueError("max_order_quantity must be >= min_order_quantity")
        return self


class ProductCreate(_ProductRules):
    model_config = ConfigDict(extra="forbid")

    category_id: int
    brand_id: int | None = None
    sku: _Sku
    barcode: _Barcode | None = None
    name: _ProductName
    description: str | None = None
    image_url: str | None = Field(default=None, max_length=255)

    unit: UnitType = UnitType.PIECE
    pack_size_label: str | None = Field(default=None, max_length=40)
    quantity_step: Quantity = Decimal("1")
    min_order_quantity: Quantity = Decimal("1")
    max_order_quantity: Quantity | None = None

    price: MoneyAmount
    compare_at_price: PositiveMoney | None = None
    cost_price: MoneyAmount | None = None
    tax_class: TaxClass = TaxClass.STANDARD
    is_age_restricted: bool = False


class ProductUpdate(_ProductRules, _PatchMixin):
    """NOTE: stock is NOT editable here; it only moves through the inventory endpoints (the ledger)"""
    model_config = ConfigDict(extra="forbid")
    _NULLABLE: ClassVar[frozenset[str]] = frozenset({"brand_id", "barcode", "description", "image_url", "pack_size_label",
                           "max_order_quantity", "compare_at_price", "cost_price"})

    category_id: int | None = None
    brand_id: int | None = None
    sku: _Sku | None = None
    barcode: _Barcode | None = None
    name: _ProductName | None = None
    description: str | None = None
    image_url: str | None = Field(default=None, max_length=255)

    unit: UnitType | None = None
    pack_size_label: str | None = Field(default=None, max_length=40)
    quantity_step: Quantity | None = None
    min_order_quantity: Quantity | None = None
    max_order_quantity: Quantity | None = None

    price: MoneyAmount | None = None
    compare_at_price: PositiveMoney | None = None
    cost_price: MoneyAmount | None = None
    tax_class: TaxClass | None = None
    is_age_restricted: bool | None = None
    is_active: bool | None = None


class ProductPublic(ORMModel):
    """what the customer app sees. NO cost_price, NO tax_class, NO stock numbers: only `in_stock`"""
    id: int
    sku: str
    barcode: str | None
    name: str
    slug: str
    description: str | None
    image_url: str | None
    category_id: int
    brand: BrandPublic | None

    unit: UnitType
    pack_size_label: str | None
    quantity_step: Decimal
    min_order_quantity: Decimal
    max_order_quantity: Decimal | None

    price: Decimal
    compare_at_price: Decimal | None
    is_age_restricted: bool

    in_stock: bool = False

    @classmethod
    def from_product(cls, product) -> "ProductPublic":
        """
        builds the schema from a Product whose `brand` and `inventory` are loaded (ProductRepository.*_full / search)
        """
        out = cls.model_validate(product)
        out.in_stock = bool(product.inventory is not None and product.inventory.available > 0)
        return out


class ProductStaff(ProductPublic):
    """STAFF / ADMIN view: adds cost, tax class and the stock balances"""
    cost_price: Decimal | None
    tax_class: TaxClass
    is_active: bool
    created_at: datetime
    updated_at: datetime

    quantity_on_hand: Decimal = Decimal("0")
    quantity_reserved: Decimal = Decimal("0")
    reorder_level: Decimal = Decimal("0")

    @classmethod
    def from_product(cls, product) -> "ProductStaff":
        out = cls.model_validate(product)
        inv = product.inventory
        if inv is not None:
            out.in_stock = inv.available > 0
            out.quantity_on_hand = inv.quantity_on_hand
            out.quantity_reserved = inv.quantity_reserved
            out.reorder_level = inv.reorder_level
        return out


class ProductQuery(BaseModel):
    """catalogue search / filter parameters (use as `Annotated[ProductQuery, Query()]`)"""
    q: str | None = Field(default=None, max_length=100)
    category_id: int | None = None
    brand_id: int | None = None
    min_price: Optional[Decimal] = Field(default=None, ge=0)
    max_price: Optional[Decimal] = Field(default=None, ge=0)
    in_stock_only: bool = False
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)
