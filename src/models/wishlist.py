# src/models/wishlist.py

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from .base import TimestampMixin

if TYPE_CHECKING:
    from .catalogue import Product
    from .customer import Customer


class WishlistItem(Base, TimestampMixin):
    """
    customer saved wishlist products persisted across devices and sessions
    """

    __tablename__ = "wishlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )

    customer: Mapped["Customer"] = relationship(lazy="raise")
    product: Mapped["Product"] = relationship(lazy="raise")

    __table_args__ = (
        UniqueConstraint("customer_id", "product_id", name="uq_wishlist_customer_product"),
        Index("idx_wishlist_customer", "customer_id"),
    )
