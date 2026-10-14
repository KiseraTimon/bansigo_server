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
