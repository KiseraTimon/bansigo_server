# src/models/admin.py

import enum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from .base import TimestampMixin, str_enum

if TYPE_CHECKING:
    from .user import User


class AdminLevel(enum.Enum):
    """
    admin power
    """
    SUPER = "super"
    OPERATIONS = "operations"
    FINANCE = "finance"


class Admin(Base, TimestampMixin):
    """
    schematic attributes for a back-office administrator
    """

    __tablename__ = "admins"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # foreign key
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # privileges
    level: Mapped[AdminLevel] = mapped_column(
        str_enum(AdminLevel), nullable=False, default=AdminLevel.OPERATIONS
    )

    # relationships
    user: Mapped["User"] = relationship(back_populates="admin", lazy="raise")
