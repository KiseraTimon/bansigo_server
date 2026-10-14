# src/models/staff.py

import enum
from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from .base import TimestampMixin, str_enum

if TYPE_CHECKING:
    from .user import User


class StaffPosition(enum.Enum):
    """
    staff obligation
    """
    STORE_MANAGER = "store_manager"
    CASHIER = "cashier"
    PICKER = "picker"                 # assembles online orders from the shelves
    STOCK_CLERK = "stock_clerk"       # receives deliveries, does stock takes
    DISPATCHER = "dispatcher"         # assigns orders to riders
    SUPPORT = "support"               # customer support


class Staff(Base, TimestampMixin):
    """
    schematic attributes for a store employee
    """

    __tablename__ = "staff"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # foreign key
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # employment details
    employee_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    position: Mapped[StaffPosition] = mapped_column(str_enum(StaffPosition), nullable=False)
    hired_on: Mapped[date] = mapped_column(Date, nullable=False)
    terminated_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # on shift
    is_on_duty: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    # relationships
    user: Mapped["User"] = relationship(back_populates="staff", lazy="raise")

    # constraints + indexes
    __table_args__ = (
        CheckConstraint(
            "terminated_on IS NULL OR terminated_on >= hired_on", name="ck_staff_employment_dates"
        ),

        Index("idx_staff_position_duty", "position", "is_on_duty"),
    )
