# src/models/delivery.py

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from .base import TimestampMixin, UTCDateTime, str_enum
from .types import Money

if TYPE_CHECKING:
    from .order import Order
    from .rider import Rider


class DeliveryStatus(enum.Enum):
    """
    schematic attributes of a rider's side of an order
    """
    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"        # offered to a rider
    ACCEPTED = "accepted"        # rider said yes
    PICKED_UP = "picked_up"      # left the shop with the parcel
    ARRIVED = "arrived"          # at the customer's pin
    DELIVERED = "delivered"
    FAILED = "failed"            # customer unreachable, refused, wrong address...
    CANCELLED = "cancelled"


class Delivery(Base, TimestampMixin):
    """
    schematic attributes of a delivery
    """

    __tablename__ = "deliveries"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # foreign keys.
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True)
    rider_id: Mapped[Optional[int]] = mapped_column(ForeignKey("riders.id", ondelete="RESTRICT"), nullable=True)

    # state & timeline
    status: Mapped[DeliveryStatus] = mapped_column(str_enum(DeliveryStatus), nullable=False, default=DeliveryStatus.UNASSIGNED)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    picked_up_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    arrived_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    failed_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # proof of delivery.
    handover_code_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    handover_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    requires_id_check: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())    # order has age-restricted items
    proof_photo_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # rider earnings
    rider_fee: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0, server_default="0")

    # reserved route algorithm fields
    estimated_distance_m: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_duration_s: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # relationships
    order: Mapped["Order"] = relationship(back_populates="delivery", lazy="raise")
    rider: Mapped[Optional["Rider"]] = relationship(back_populates="deliveries", lazy="raise")

    # constraints + indexes
    __table_args__ = (
        # past the "unassigned" stage a delivery must have a rider
        CheckConstraint(
            "status IN ('unassigned', 'cancelled') OR rider_id IS NOT NULL",
            name="ck_delivery_has_rider",
        ),

        CheckConstraint(
            "status <> 'delivered' OR delivered_at IS NOT NULL",
            name="ck_delivery_delivered_has_time",
        ),

        CheckConstraint("rider_fee >= 0", name="ck_delivery_rider_fee_non_negative"),

        Index("idx_delivery_rider_status", "rider_id", "status"),
        Index("idx_delivery_status", "status"),
    )
