# src/models/recommendation.py

from typing import Optional
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from .base import TimestampMixin


class RecommendationEvent(Base, TimestampMixin):
    """
    Tracks interactions with recommended products to study acceptance rate,
    helpfulness, conversion, and comparative performance between Apriori and FP-Growth.
    """

    __tablename__ = "recommendation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    algorithm: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # "apriori" | "fpgrowth"
    event_type: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True
    )  # "impression" | "click" | "add_to_cart" | "purchase" | "helpful" | "unhelpful"
    context: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # "home" | "product_details" | "cart"
    session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    rating: Mapped[Optional[int]] = mapped_column(nullable=True)  # 1-5 rating for usability / helpfulness
    feedback_text: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
