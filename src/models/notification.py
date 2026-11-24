# src/models/notification.py

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from .base import TimestampMixin


class Notification(Base, TimestampMixin):
    """
    Persistent user notification for customers and riders (pickup codes, status updates, SLA alerts, penalties).
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False, default="system")
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    external_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    action_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    action_payload: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_notification_user_read", "user_id", "is_read"),
        Index("idx_notification_user_deleted", "user_id", "is_deleted"),
    )
