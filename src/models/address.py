# src/models/address.py

from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from .base import AuditMixin, TimestampMixin
from .types import Coordinate, Money

if TYPE_CHECKING:
    from .customer import Customer


class DeliveryZone(Base, AuditMixin):
    """
    schematic properties of an area the shop delivers to
    """

    __tablename__ = "delivery_zones"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # zone fields
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    delivery_fee: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0, server_default="0")
    min_order_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0, server_default="0")
    estimated_minutes: Mapped[Optional[int]] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    # constraints
    __table_args__ = (
        CheckConstraint("delivery_fee >= 0", name="ck_zone_fee_non_negative"),
        CheckConstraint("min_order_amount >= 0", name="ck_zone_min_order_non_negative"),
    )


class Address(Base, TimestampMixin):
    """
    schematic properties of a saved delivery address of a customer.
    """

    __tablename__ = "addresses"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # foreign keys
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    zone_id: Mapped[Optional[int]] = mapped_column(ForeignKey("delivery_zones.id", ondelete="SET NULL"), nullable=True)

    # who receives (may not be the account holder)
    label: Mapped[str] = mapped_column(String(30), nullable=False, default="Home")
    recipient_name: Mapped[str] = mapped_column(String(100), nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String(30), nullable=False)    # +2547XXXXXXXX

    # where
    area: Mapped[str] = mapped_column(String(100), nullable=False)               # estate / neighbourhood
    street_address: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    landmark: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # "opposite Equity Bank"
    directions: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)    # "green gate, 2nd floor"
    latitude: Mapped[Decimal] = mapped_column(Coordinate, nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Coordinate, nullable=False)

    # the pre-selected one at checkout. At most one per customer: enforced by the service
    # (MySQL has no partial unique index)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    # relationships
    customer: Mapped["Customer"] = relationship(back_populates="addresses", lazy="raise")
    zone: Mapped[Optional["DeliveryZone"]] = relationship(lazy="raise")

    # constraints + indexes
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_address_latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_address_longitude_range"),
        Index("idx_address_customer", "customer_id"),
    )
