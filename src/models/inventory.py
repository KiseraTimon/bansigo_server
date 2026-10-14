# src/models/inventory.py

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from .base import TimestampMixin, UTCDateTime, str_enum
from .types import BigIntPK, Money, Quantity

if TYPE_CHECKING:
    from .catalogue import Product
    from .supplier import Supplier


class Inventory(Base, TimestampMixin):
    """
    schematic attributes of stock of one product
    """

    __tablename__ = "inventory"

    # primary key
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )

    # balances
    quantity_on_hand: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=0, server_default="0")    # physically on the shelf/store room
    quantity_reserved: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=0, server_default="0")   # promised to open orders, not yet picked

    # restocking
    reorder_level: Mapped[Decimal] = mapped_column(Quantity, nullable=False, default=0, server_default="0")       # at or below this: flag for reorder
    reorder_quantity: Mapped[Optional[Decimal]] = mapped_column(Quantity, nullable=True)                          # suggested order size
    last_counted_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)                       # last physical stock take

    # optimistic locking
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version}

    # relationships
    product: Mapped["Product"] = relationship(back_populates="inventory", lazy="raise")

    # constraints
    __table_args__ = (
        CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_on_hand_non_negative"),
        CheckConstraint("quantity_reserved >= 0", name="ck_inventory_reserved_non_negative"),

        CheckConstraint("quantity_reserved <= quantity_on_hand", name="ck_inventory_reserved_within_on_hand"),
    )

    # derived properties
    @hybrid_property
    def available(self) -> Decimal:
        return self.quantity_on_hand - self.quantity_reserved


class MovementType(enum.Enum):
    """
    enum mapping why stock moved
    """
    OPENING = "opening"          # initial count when the shop starts using the system
    RECEIPT = "receipt"          # delivery from a supplier
    SALE = "sale"                # picked for an order
    RETURN = "return"            # customer return that is resellable
    WASTAGE = "wastage"          # expired, damaged, stolen
    ADJUSTMENT = "adjustment"    # stock-take correction


class StockMovement(Base):
    """
    schematic attributes of one line of the stock ledger.
    """

    __tablename__ = "stock_movements"

    # primary key
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)

    # foreign keys
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True)
    performed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # the movement
    movement_type: Mapped[MovementType] = mapped_column(str_enum(MovementType), nullable=False)
    quantity_change: Mapped[Decimal] = mapped_column(Quantity, nullable=False)    # signed: +50 received, -2 sold
    quantity_after: Mapped[Decimal] = mapped_column(Quantity, nullable=False)     # on-hand right after: lets you read history without re-adding
    unit_cost: Mapped[Optional[Decimal]] = mapped_column(Money, nullable=True)    # purchase cost per unit (receipts)

    # what caused stock movement
    reference_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # timestamping
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())

    # relationships
    product: Mapped["Product"] = relationship(lazy="raise")
    supplier: Mapped[Optional["Supplier"]] = relationship(lazy="raise")

    # constraints + indexes
    __table_args__ = (
        CheckConstraint("quantity_change <> 0", name="ck_stock_movement_non_zero"),
        CheckConstraint("quantity_after >= 0", name="ck_stock_movement_balance_non_negative"),
        Index("idx_stock_movement_product_time", "product_id", "created_at"),
        Index("idx_stock_movement_reference", "reference_type", "reference_id"),
    )
