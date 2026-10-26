# src/models/review.py

import enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from .base import TimestampMixin, str_enum

if TYPE_CHECKING:
    from .catalogue import Product
    from .customer import Customer
    from .order import Order
    from .rider import Rider


class ReviewTargetType(enum.Enum):
    PRODUCT = "product"
    RIDER = "rider"
    DELIVERY = "delivery"
    GENERAL = "general"


class Review(Base, TimestampMixin):
    """
    schematic attributes for customer reviews, feedback and ratings
    """

    __tablename__ = "reviews"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # foreign keys
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    rider_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("riders.id", ondelete="SET NULL"), nullable=True
    )
    product_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )

    # details
    target_type: Mapped[ReviewTargetType] = mapped_column(
        str_enum(ReviewTargetType), nullable=False, default=ReviewTargetType.PRODUCT
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sentiment: Mapped[str] = mapped_column(String(20), nullable=False, default="positive")
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    # relationships
    customer: Mapped["Customer"] = relationship(lazy="raise")
    order: Mapped[Optional["Order"]] = relationship(lazy="raise")
    rider: Mapped[Optional["Rider"]] = relationship(lazy="raise")
    product: Mapped[Optional["Product"]] = relationship(lazy="raise")

    # constraints & indexes
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating_range"),
        Index("idx_review_customer", "customer_id"),
        Index("idx_review_target", "target_type", "is_published"),
        Index("idx_review_product", "product_id"),
        Index("idx_review_rider", "rider_id"),
    )
