# src/models/user.py

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Boolean, Index, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from .base import TimestampMixin, UTCDateTime, str_enum

if TYPE_CHECKING:
    from .customer import Customer


# user roles
class UserRole(enum.Enum):
    CUSTOMER = "customer"
    CLIENT = "client"
    RIDER = "rider"
    STAFF = "staff"
    ADMIN = "admin"


# user model
class User(Base, TimestampMixin):
    """
    schematic attributes of a user
    """

    __tablename__ = "users"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # profile fields
    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_name: Mapped[str] = mapped_column(String(50), nullable=False)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    phone: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    picture: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)

    # credentials
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # server fields
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole), nullable=False, default=UserRole.CUSTOMER)

    # truth fields
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # timestamp fields
    last_login: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)

    # relationships
    customer: Mapped[Optional["Customer"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False
    )

    # indexes
    __table_args__ = (
        Index('idx_user_role_active', 'role', 'is_active'),
    )
