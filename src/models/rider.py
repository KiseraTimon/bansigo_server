# src/models/rider.py

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from .base import TimestampMixin, UTCDateTime, str_enum
from .types import Coordinate

if TYPE_CHECKING:
    from .user import User


class ApprovalStatus(enum.Enum):
    """
    vetting state of a rider.
    """
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class RiderStatus(enum.Enum):
    """
    what the rider is doing right now
    """
    OFFLINE = "offline"
    AVAILABLE = "available"
    BUSY = "busy"


class VehicleType(enum.Enum):
    """
    what vehicle the rider is operating
    """
    BICYCLE = "bicycle"
    MOTORCYCLE = "motorcycle"    # boda boda
    TUKTUK = "tuktuk"
    CAR = "car"


class Rider(Base, TimestampMixin):
    """
    schematic attributes for a delivery rider.
    """

    __tablename__ = "riders"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # foreign key
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # vetting
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        str_enum(ApprovalStatus), nullable=False, default=ApprovalStatus.PENDING
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    approved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # identity documents.
    national_id_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, unique=True)
    licence_number: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    licence_expiry: Mapped[Optional[date]] = mapped_column(Date, nullable=True)    # null for bicycles

    # vehicle
    vehicle_type: Mapped[VehicleType] = mapped_column(
        str_enum(VehicleType), nullable=False, default=VehicleType.MOTORCYCLE
    )
    vehicle_plate: Mapped[Optional[str]] = mapped_column(String(15), nullable=True, unique=True)
    vehicle_description: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # availability + last known position
    # TODO: Migrate these to REDIS as they are constantly updated fields
    status: Mapped[RiderStatus] = mapped_column(
        str_enum(RiderStatus), nullable=False, default=RiderStatus.OFFLINE
    )
    last_latitude: Mapped[Optional[Decimal]] = mapped_column(Coordinate, nullable=True)
    last_longitude: Mapped[Optional[Decimal]] = mapped_column(Coordinate, nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)

    # denormalized statistics
    rating_average: Mapped[Optional[Decimal]] = mapped_column(Numeric(3, 2), nullable=True)
    rating_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    deliveries_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # relationships
    user: Mapped["User"] = relationship(back_populates="rider", foreign_keys=[user_id], lazy="raise")
    # deliveries: Mapped[list["Delivery"]] = relationship(back_populates="rider", lazy="raise")

    # constraints + indexes
    __table_args__ = (
        CheckConstraint("last_latitude BETWEEN -90 AND 90", name="ck_rider_latitude_range"),
        CheckConstraint("last_longitude BETWEEN -180 AND 180", name="ck_rider_longitude_range"),

        # a position is either complete or absent
        CheckConstraint(
            "(last_latitude IS NULL) = (last_longitude IS NULL)", name="ck_rider_position_complete"
        ),
        CheckConstraint("rating_average BETWEEN 0 AND 5", name="ck_rider_rating_range"),

        # the dispatcher's query: approved riders who are available
        Index("idx_rider_dispatch", "approval_status", "status"),
    )
