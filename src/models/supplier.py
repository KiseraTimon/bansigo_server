# src/models/supplier.py

from typing import Optional

from sqlalchemy import Boolean, Integer, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from .base import AuditMixin


class Supplier(Base, AuditMixin):
    """
    schematic attributes of parties Bansi buys stock from
    """

    __tablename__ = "suppliers"

    # primary key
    id: Mapped[int] = mapped_column(primary_key=True)

    # supplier fields
    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kra_pin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
