# src/models/client.py

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from .base import TimestampMixin


class Customer(Base, TimestampMixin):
    """
    schematic attributes for a customer
    """

    __tablename__ = "customers"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # foreign key
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)

    # customer fields
    loyalty_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_premium: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    # relationships
    user: Mapped["User"] = relationship(back_populates="customer")

    # constraints
    __table_args__ = (
        CheckConstraint("loyalty_points >= 0", name="ck_customer_loyalty_points_non_negative"),
    )

