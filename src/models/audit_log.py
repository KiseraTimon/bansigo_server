# src/models/audit_log.py

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import ForeignKey, Index, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from .base import UTCDateTime
from .types import BigIntPK


class AuditLog(Base):
    """
    schematic attributes of who changed what i.e during
    price edits, stock adjustments, refund approvals, role changes,
    manual payment matching etc.
    """

    __tablename__ = "audit_logs"

    # primary key
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)

    # who
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # what
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(40), nullable=False)    # str: ids may be composite

    # before / after snapshots of only the fields that changed
    before: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    after: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # where from
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)    # fits IPv6
    request_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())

    # indexes
    __table_args__ = (
        Index("idx_audit_entity", "entity_type", "entity_id"),
        Index("idx_audit_actor_time", "actor_user_id", "created_at"),
    )
