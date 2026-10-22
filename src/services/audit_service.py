# src/services/audit_service.py

"""
writes the 'who changed what' trail (price edits, stock adjustments, refund approvals, rider vetting ...).
record() only STAGES the row: it commits together with the change it describes, so the two can never disagree.
"""

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AuditLog
from utilities.logs import request_id_var


def jsonable(value: Any) -> Any:
    """
    the JSON columns cannot hold Decimal / Enum / datetime, so snapshots are converted first
    :param value: Any
    :return: Any
    """
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


class AuditService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def record(
        self,
        *,
        actor_id: int | None,
        action: str,
        entity_type: str,
        entity_id: int | str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        """
        :param actor_id: int | None
        :param action: str
        :param entity_type: str
        :param entity_id: int | str
        :param before: dict | None
        :param after: dict | None
        :return: None
        """
        request_id = request_id_var.get()
        self.db.add(AuditLog(
            actor_user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            before=jsonable(before) if before else None,
            after=jsonable(after) if after else None,
            request_id=None if request_id == "-" else request_id,
        ))
