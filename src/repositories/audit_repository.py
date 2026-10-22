# src/repositories/audit_repository.py

from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AuditLog
from .base_repository import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    """audits are append-only: there is deliberately no update or delete here"""

    def __init__(self, db: AsyncSession):
        super().__init__(AuditLog, db)
