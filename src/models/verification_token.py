# src/models/verification_token.py

import enum
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from .base import TimestampMixin, UTCDateTime, str_enum


class TokenPurpose(enum.Enum):
    """
    purpose options for verification tokens
    """
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"


class VerificationToken(Base, TimestampMixin):
    """
    schematic attributes for verification tokens
    """

    __tablename__ = "verification_tokens"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # foreign key
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # token fields
    purpose: Mapped[TokenPurpose] = mapped_column(str_enum(TokenPurpose), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # constraints
    __table_args__ = (
        UniqueConstraint("user_id", "purpose", name="uq_token_user_purpose"),
    )
