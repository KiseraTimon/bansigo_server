# src/models/order.py
"""
an order and everything that hangs off it.

SNAPSHOT RULE: an order must read the same in five years. Prices, product names, tax rates and
the delivery address are COPIED onto the order at checkout. Editing a product or an address
later must never rewrite history (receipts, refunds and KRA records depend on it)

MONEY (KES, VAT-inclusive):
    total = subtotal + delivery_fee - discount_total + rounding_adjustment
M-Pesa STK Push only takes whole shillings, so `rounding_adjustment` carries the cents needed
to make `total` a whole number for M-Pesa orders
"""

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from .base import TimestampMixin, UTCDateTime, str_enum
from .catalogue import TaxClass, UnitType
from .types import BigIntPK, Coordinate, Money, Quantity, Rate

if TYPE_CHECKING:
    from .address import Address
    from .catalogue import Product
    from .customer import Customer
    from .delivery import Delivery
    from .staff import Staff


class OrderStatus(enum.Enum):
    """
    order lifeline
    """

    PENDING_PAYMENT = "pending_payment"    # created; waiting for the M-Pesa result; where cash is chosen, it goes straight to CONFIRMED
    CONFIRMED = "confirmed"                # paid (or cash accepted); stock is reserved
    PREPARING = "preparing"                # a picker is assembling it
    READY = "ready"                        # packed: waiting for a rider / for the customer to collect
    OUT_FOR_DELIVERY = "out_for_delivery"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class OrderPaymentStatus(enum.Enum):
    """
    cached summary of the order's payments
    """

    UNPAID = "unpaid"
    PAID = "paid"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"


class PaymentMethod(enum.Enum):
    """
    what the customer CHOSE at checkout (a Payment row records how a payment actually happened)
    """

    MPESA = "mpesa"
    CASH = "cash"


class FulfilmentType(enum.Enum):
    DELIVERY = "delivery"
    PICKUP = "pickup"      # click & collect


class Order(Base, TimestampMixin):
    """
    schematic attributes of an order. created_at is the moment it was placed
    """

    __tablename__ = "orders"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # public reference
    order_number: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)

    # foreign keys
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    address_id: Mapped[Optional[int]] = mapped_column(ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True)
    assigned_picker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("staff.id", ondelete="SET NULL"), nullable=True)
    cancelled_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # state
    status: Mapped[OrderStatus] = mapped_column(str_enum(OrderStatus), nullable=False, default=OrderStatus.PENDING_PAYMENT)
    payment_status: Mapped[OrderPaymentStatus] = mapped_column(
        str_enum(OrderPaymentStatus), nullable=False, default=OrderPaymentStatus.UNPAID
    )
    payment_method: Mapped[PaymentMethod] = mapped_column(str_enum(PaymentMethod), nullable=False, default=PaymentMethod.MPESA)
    fulfilment_type: Mapped[FulfilmentType] = mapped_column(
        str_enum(FulfilmentType), nullable=False, default=FulfilmentType.DELIVERY
    )

    # client-generated key
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # money
    subtotal: Mapped[Decimal] = mapped_column(Money, nullable=False)
    delivery_fee: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0, server_default="0")
    discount_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0, server_default="0")
    rounding_adjustment: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0, server_default="0")
    total: Mapped[Decimal] = mapped_column(Money, nullable=False)           # what the customer is asked to pay
    tax_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0, server_default="0")    # VAT CONTAINED in total (informational, for invoices)
    adjusted_total: Mapped[Optional[Decimal]] = mapped_column(Money, nullable=True)

    # delivery snapshot
    delivery_recipient_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    delivery_recipient_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    delivery_address_text: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    delivery_latitude: Mapped[Optional[Decimal]] = mapped_column(Coordinate, nullable=True)
    delivery_longitude: Mapped[Optional[Decimal]] = mapped_column(Coordinate, nullable=True)

    # notes + scheduling
    customer_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)    # chosen delivery slot

    # lifecycle timestamps (created_at = placed)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # relationships
    customer: Mapped["Customer"] = relationship(back_populates="orders", lazy="raise")
    address: Mapped[Optional["Address"]] = relationship(lazy="raise")
    assigned_picker: Mapped[Optional["Staff"]] = relationship(lazy="raise")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="raise"
    )
    status_history: Mapped[list["OrderStatusHistory"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderStatusHistory.id", lazy="raise"
    )
    delivery: Mapped[Optional["Delivery"]] = relationship(back_populates="order", uselist=False, lazy="raise")
    # payments: Mapped[list["Payment"]] = relationship(back_populates="order", lazy="raise")

    # constraints + indexes
    __table_args__ = (
        UniqueConstraint("customer_id", "idempotency_key", name="uq_order_customer_idempotency"),
        CheckConstraint(
            "subtotal >= 0 AND delivery_fee >= 0 AND discount_total >= 0 AND total >= 0",
            name="ck_order_amounts_non_negative",
        ),
        # the arithmetic is enforced by the database, not just trusted from the code
        CheckConstraint(
            "total = subtotal + delivery_fee - discount_total + rounding_adjustment",
            name="ck_order_total_matches_parts",
        ),
        # a delivery order must carry a destination the rider can navigate to
        CheckConstraint(
            "fulfilment_type = 'pickup' OR (delivery_address_text IS NOT NULL "
            "AND delivery_latitude IS NOT NULL AND delivery_longitude IS NOT NULL)",
            name="ck_order_delivery_has_destination",
        ),
        Index("idx_order_customer_time", "customer_id", "created_at"),
        Index("idx_order_status_time", "status", "created_at"),
    )


class PickStatus(enum.Enum):
    """
    what happened when a picker went to the shelf for this line
    """

    PENDING = "pending"
    PICKED = "picked"
    SHORT = "short"                  # fewer than ordered were available
    OUT_OF_STOCK = "out_of_stock"
    SUBSTITUTED = "substituted"      # replaced by another product (customer is told)


class OrderItem(Base):
    """
    schematic properties of one product line on an order
    """

    __tablename__ = "order_items"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # foreign keys. RESTRICT: a product that was ever sold can't be deleted (deactivate it)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    substitute_product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )

    # snapshot of the product at checkout
    product_name: Mapped[str] = mapped_column(String(150), nullable=False)
    sku: Mapped[str] = mapped_column(String(40), nullable=False)
    unit: Mapped[UnitType] = mapped_column(str_enum(UnitType), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_class: Mapped[TaxClass] = mapped_column(str_enum(TaxClass), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Rate, nullable=False, default=0, server_default="0")

    # ordered vs picked
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    quantity_picked: Mapped[Optional[Decimal]] = mapped_column(Quantity, nullable=True)
    pick_status: Mapped[PickStatus] = mapped_column(str_enum(PickStatus), nullable=False, default=PickStatus.PENDING)

    # line money
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False)                  # round(unit_price * quantity, 2)
    final_line_total: Mapped[Optional[Decimal]] = mapped_column(Money, nullable=True)   # after picking

    # relationships
    order: Mapped["Order"] = relationship(back_populates="items", lazy="raise")
    product: Mapped["Product"] = relationship(foreign_keys=[product_id], lazy="raise")

    # constraints + indexes
    __table_args__ = (
        UniqueConstraint("order_id", "product_id", name="uq_order_item_product"),
        CheckConstraint("quantity > 0", name="ck_order_item_quantity_positive"),
        CheckConstraint("quantity_picked IS NULL OR quantity_picked >= 0", name="ck_order_item_picked_non_negative"),
        CheckConstraint("unit_price >= 0 AND line_total >= 0", name="ck_order_item_money_non_negative"),
        Index("idx_order_item_product", "product_id"),    # "which orders contained product X?"
    )


class OrderStatusHistory(Base):
    """
    every status change, with who and when. Feeds the customer's tracking timeline,
    support ("when did it leave the shop?") and disputes. Insert only
    """

    __tablename__ = "order_status_history"

    # primary key
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)

    # foreign keys
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    changed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # transition properties
    from_status: Mapped[Optional[OrderStatus]] = mapped_column(str_enum(OrderStatus), nullable=True)
    to_status: Mapped[OrderStatus] = mapped_column(str_enum(OrderStatus), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())

    # relationships
    order: Mapped["Order"] = relationship(back_populates="status_history", lazy="raise")

    # indexes
    __table_args__ = (
        Index("idx_order_history_order_time", "order_id", "created_at"),
    )
