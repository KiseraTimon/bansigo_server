# src/models/catalogue.py

import enum
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from .base import AuditMixin, str_enum
from .types import Money, Quantity

if TYPE_CHECKING:
    from .inventory import Inventory


class UnitType(enum.Enum):
    """
    the unit the price is quoted in i.e.
    a 500 g packet of sugar is 1 PIECE; loose tomatoes are priced per KG
    """

    PIECE = "piece"
    KG = "kg"
    LITRE = "litre"


class TaxClass(enum.Enum):
    """
    VAT treatment.
    Assumptions:
        Shelf prices are VAT-inclusive, where, the class says how much of the price is tax.

    STANDARD   - standard rate (16%)
    ZERO_RATED - taxable at 0%
    EXEMPT     - outside VAT
    """

    # TODO: Reminder
    """
        Which products fall in which class should be a decision from the shop's accountant; KRA's e-invoicing
        (eTIMS) may also need item classification codes later
    """

    STANDARD = "standard"
    ZERO_RATED = "zero_rated"
    EXEMPT = "exempt"


class Category(Base, AuditMixin):
    """
    schematic properties of a node in the catalogue tree
    """

    __tablename__ = "categories"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # foreign key
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )

    # category fields
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    # relationships
    parent: Mapped[Optional["Category"]] = relationship(
        back_populates="children", remote_side="Category.id", lazy="raise"
    )
    children: Mapped[list["Category"]] = relationship(back_populates="parent", lazy="raise")

    # constraints
    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_category_parent_name"),
    )


class Brand(Base, AuditMixin):
    """
    schematic properties of a product brand e.g. Brookside, Omo
    """

    __tablename__ = "brands"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # brand fields
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())


class Product(Base, AuditMixin):
    """
    schematic properties of one sellable item (one SKU):
        -   variants are separate products.
        -   sizes are different barcodes and different prices, and
            treating them as one product with options complicates stock, pricing and recommendations
    """

    __tablename__ = "products"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # foreign keys
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    brand_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("brands.id", ondelete="SET NULL"), nullable=True
    )

    # identification
    sku: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)         # internal reference code
    barcode: Mapped[Optional[str]] = mapped_column(String(14), nullable=True, unique=True)    # EAN/UPC/GTIN
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(170), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gallery_images: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True, default=list)

    # sale properties
    unit: Mapped[UnitType] = mapped_column(str_enum(UnitType), nullable=False, default=UnitType.PIECE)
    pack_size_label: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    quantity_step: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=1, server_default="1")
    min_order_quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=1, server_default="1")
    max_order_quantity: Mapped[Optional[Decimal]] = mapped_column(Quantity, nullable=True)

    # money: KES, VAT-inclusive
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)                          # current selling price per `unit`
    compare_at_price: Mapped[Optional[Decimal]] = mapped_column(Money, nullable=True)      # the struck-through "was" price
    cost_price: Mapped[Optional[Decimal]] = mapped_column(Money, nullable=True)            # last purchase cost: STAFF/ADMIN ONLY, never in a public schema
    tax_class: Mapped[TaxClass] = mapped_column(str_enum(TaxClass), nullable=False, default=TaxClass.STANDARD)

    # flags
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())    # visible in the app
    is_age_restricted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())    # alcohol/tobacco: rider must check ID

    # relationships
    category: Mapped["Category"] = relationship(lazy="raise")
    brand: Mapped[Optional["Brand"]] = relationship(lazy="raise")
    inventory: Mapped[Optional["Inventory"]] = relationship(back_populates="product", uselist=False, lazy="raise")

    # constraints + indexes
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_product_price_non_negative"),
        CheckConstraint("compare_at_price IS NULL OR compare_at_price > price", name="ck_product_compare_price"),
        CheckConstraint("cost_price >= 0", name="ck_product_cost_non_negative"),
        CheckConstraint("quantity_step > 0", name="ck_product_step_positive"),
        CheckConstraint("min_order_quantity > 0", name="ck_product_min_qty_positive"),
        CheckConstraint(
            "max_order_quantity IS NULL OR max_order_quantity >= min_order_quantity",
            name="ck_product_max_qty",
        ),
        Index("idx_product_category_active", "category_id", "is_active"),
        Index("idx_product_name", "name"),
    )
